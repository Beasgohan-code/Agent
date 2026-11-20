"""Explicit antiflood commands and bounded process-local message counters."""

import re
import asyncio
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from pyrogram.enums import ChatType
from ...platform.antispam import read_policy, change_policy, PolicyError
from ...platform.group_trust import trusted_members
from ...ui.tables import panel, kv_table
from ...utils.rich import reply

COMMANDS = ("flood", "setflood", "setfloodtimer", "floodmode", "clearflood")


def duration(text):
    match = re.fullmatch(r"([1-9][0-9]{0,7})([smhdw])", text.lower())
    if not match:
        raise ValueError("Use a duration such as 30s, 4m, 3h, 6d or 5w.")
    seconds = int(match[1]) * dict(s=1, m=60, h=3600, d=86400, w=604800)[match[2]]
    if not 30 <= seconds <= 365 * 86400:
        raise ValueError("Duration must be between 30 seconds and 365 days.")
    return seconds


class FloodInputError(ValueError):
    """Locally authored input/authorization error, safe to display."""


def setting(command,args):
    hints={
        'flood':'Use /flood without arguments.',
        'setflood':'Use /setflood 7 or /setflood off. Count: 2–1000.',
        'setfloodtimer':'Use /setfloodtimer 10 30s or /setfloodtimer off. Count: 2–1000; window: 30s–1d.',
        'floodmode':'Use /floodmode ban|mute|kick or /floodmode tmute 5m (also tban).',
        'clearflood':'Use /clearflood on or /clearflood off.',
    }
    args=[arg.lower() for arg in args]
    def count(value):
        return int(value) if value.isascii() and value.isdecimal() and len(value)<=4 else -1
    if command=='flood' and not args:
        return None,None
    if command=='setflood' and len(args)==1:
        value=0 if args[0] in ('off','no','0') else count(args[0])
        if value==0 or 2<=value<=1000:
            return 'consecutive',value
    if command=='setfloodtimer':
        if len(args)==1 and args[0] in ('off','no'):
            return 'floodtimer',(0,0)
        if len(args)==2 and 2<=count(args[0])<=1000:
            try:
                seconds=duration(args[1])
            except ValueError:
                raise FloodInputError(hints[command]) from None
            if seconds<=86400:
                return 'floodtimer',(count(args[0]),seconds)
    if command=='floodmode':
        if len(args)==1 and args[0] in ('ban','mute','kick'):
            return 'floodmode',(args[0],0)
        if len(args)==2 and args[0] in ('tban','tmute'):
            try:
                return 'floodmode',(args[0],duration(args[1]))
            except ValueError:
                raise FloodInputError('Timed actions: 30s–365d. Example: /floodmode tmute 5m') from None
    if command=='clearflood' and len(args)==1 and args[0] in ('yes','no','on','off'):
        return 'clearflood',args[0] in ('yes','on')
    raise FloodInputError(hints[command])


def build(ctx):
    from . import is_moderator,duration_label
    import logging
    logger=logging.getLogger(__name__)

    def handler(command):
        async def call(client,message):
            user=getattr(message,'from_user',None)
            committed=False
            async def authorized():
                return await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5)
            try:
                if (getattr(getattr(message,'chat',None),'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise FloodInputError('Use your personal administrator account in a group.')
                if not await authorized():
                    raise FloodInputError('Current Manage chat permission required.')
                operation,value=setting(command,(getattr(message,'text','') or '').split()[1:])
                if operation is None:
                    policy=await read_policy(ctx,message.chat.id)
                else:
                    if not await authorized():
                        raise FloodInputError('Administrator permissions changed. No settings changed.')
                    policy=await change_policy(ctx,message.chat.id,operation,value,actor=user.id)
                    committed=True
                if not await authorized():
                    raise FloodInputError('Settings saved; permissions changed. Details withheld.' if committed else 'Administrator permissions changed. Settings withheld.')
                consecutive=policy.get('consecutive_limit',0)
                count=policy.get('timed_flood_count',0)
                action=policy.get('flood_action','mute')
                if action in ('tmute','tban'):
                    action+=' · '+duration_label(policy.get('flood_action_seconds',0))
                burst=f"{policy['flood_messages']} per {duration_label(policy['flood_window_seconds'])} · {policy['action']}" if policy['flood_enabled'] else 'Off'
                await reply(message,panel('Antiflood',icon=ctx.theme.emoji('shield'),table=kv_table([
                    ('Moderator',str(user.id)),('Status','Saved' if committed else 'Current saved settings'),
                    ('Consecutive messages',str(consecutive) if consecutive else 'Off'),
                    ('Timed messages',f"{count} per {duration_label(policy.get('timed_flood_seconds',0))}" if count else 'Off'),
                    ('Burst limiter',burst),('Consecutive/timed action',action),
                    ('Delete triggering messages','On' if policy.get('clear_flood',True) else 'Off')]),
                    note='/setflood 7 · /setfloodtimer 10 30s\n/floodmode tmute 5m · /clearflood on\nCounts reset on restart. Saved settings need a running watcher and bot permissions.'))
            except (FloodInputError,PolicyError) as error:
                await reply(message,str(error))
            except Exception as error:
                logger.warning('#Errors Antiflood settings unavailable (%s)',type(error).__name__)
                await reply(message,'Settings saved; display or permissions unconfirmed. Check /flood.' if committed else 'Settings or permissions unconfirmed. Check /flood before retrying.')
        return call
    return {command:handler(command) for command in COMMANDS}


class Counter:
    """Bounded chat streaks and per-member windows; no message contents retained."""

    def __init__(self):
        self.streaks = OrderedDict()
        self.windows = OrderedDict()

    def note(self, chat, user, message_id, policy, now=None):
        now = time.monotonic() if now is None else now
        signature = (
            policy.get("consecutive_limit", 0),
            policy.get("timed_flood_count", 0),
            policy.get("timed_flood_seconds", 0),
        )
        previous, ids, old_signature = self.streaks.pop(
            chat, (None, deque(maxlen=1000), None)
        )
        if previous != user or signature != old_signature:
            ids = deque(maxlen=1000)
        ids.append(message_id)
        self.streaks[chat] = (user, ids, signature)
        key = (chat, user)
        stamps, old = self.windows.pop(key, (deque(maxlen=1000), None))
        if old != signature:
            stamps.clear()
        stamps.append((now, message_id))
        window = policy.get("timed_flood_seconds", 0)
        while stamps and now - stamps[0][0] > window:
            stamps.popleft()
        self.windows[key] = (stamps, signature)
        while len(self.streaks) > 1000:
            self.streaks.popitem(last=False)
        while len(self.windows) > 2000:
            self.windows.popitem(last=False)
        if signature[0] and len(ids) >= signature[0]:
            return list(ids)
        if signature[1] and len(stamps) >= signature[1]:
            return [mid for _, mid in stamps]
        return []

    def clear(self, chat, user):
        self.streaks.pop(chat, None)
        self.windows.pop((chat, user), None)


def watch(ctx):
    from . import (
        is_moderator,
        target_is_protected,
        kick_member,
        MUTE_PERMISSIONS,
        PartialKickError,
    )
    import logging

    logger = logging.getLogger(__name__)
    counter = Counter()

    async def call(client, message):
        chat, user = getattr(message, "chat", None), getattr(message, "from_user", None)
        if getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return
        if (
            user is None
            or getattr(message, "sender_chat", None) is not None
            or getattr(message, "service", None)
        ):
            counter.streaks.pop(chat.id, None)
            return
        try:
            policy = await read_policy(ctx, chat.id)
            if not policy.get("consecutive_limit") and not policy.get(
                "timed_flood_count"
            ):
                counter.streaks.pop(chat.id, None)
                for key in list(counter.windows):
                    if key[0] == chat.id:
                        counter.windows.pop(key, None)
                return
            ids = counter.note(chat.id, user.id, message.id, policy)
            if user.id in await trusted_members(ctx, chat.id) or await is_moderator(
                client, message
            ):
                counter.clear(chat.id, user.id)
                return
            if not ids or await target_is_protected(client, chat.id, user.id):
                return
            counter.clear(chat.id, user.id)
            mode = policy.get("flood_action", "mute")
            kwargs = (
                {
                    "until_date": datetime.now(timezone.utc)
                    + timedelta(seconds=policy["flood_action_seconds"])
                }
                if mode in ("tban", "tmute")
                else {}
            )
            if mode in ("ban", "tban"):
                result = await client.ban_chat_member(chat.id, user.id, **kwargs)
            elif mode in ("mute", "tmute"):
                result = await client.restrict_chat_member(
                    chat.id, user.id, MUTE_PERMISSIONS, **kwargs
                )
            elif mode == "kick":
                result = True
                await kick_member(client, ctx, chat.id, user.id, source="antiflood")
            else:
                return
            if result is not True:
                await reply(
                    message,
                    "Antiflood action was not confirmed. Check current Telegram state.",
                )
                return
            ctx.chats.log(
                chat.id, "antiflood:" + mode, actor_id=None, target_id=user.id
            )
            cleanup = ""
            if policy.get("clear_flood", True):
                try:
                    for start in range(0, len(ids), 100):
                        deleted = await client.delete_messages(
                            chat.id, ids[start : start + 100]
                        )
                        if deleted is not True:
                            cleanup = " Message cleanup was not confirmed."
                except Exception:
                    cleanup = " Message cleanup was not confirmed."
            await reply(
                message, f"Antiflood: {mode} applied to member {user.id}.{cleanup}"
            )
        except PartialKickError as error:
            await reply(message, str(error))
        except Exception:
            logger.warning(
                "Antiflood action unavailable or unconfirmed; check Telegram state before retrying."
            )

    locks = {}

    async def serialized(client, message):
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if chat_id not in locks:
            if len(locks) >= 1000:
                return
            locks[chat_id] = [asyncio.Lock(), 0]
        entry = locks[chat_id]
        entry[1] += 1
        try:
            async with entry[0]:
                await call(client, message)
        finally:
            entry[1] -= 1
            if not entry[1]:
                locks.pop(chat_id, None)

    return serialized
