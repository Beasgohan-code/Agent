"""Explicit antiflood commands and bounded process-local message counters."""

import re
import asyncio
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from pyrogram.enums import ChatType
from ...platform.antispam import read_policy, change_policy, PolicyError
from ...platform.group_trust import trusted_members
from ...platform.admin_settings import denied
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


def build(ctx):
    from . import is_moderator

    def handler(command):
        async def call(client, message):
            user = getattr(message, "from_user", None)
            if (
                getattr(getattr(message, "chat", None), "type", None)
                not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or type(getattr(user, "id", None)) is not int
                or user.id <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use antiflood commands as yourself inside the group."
                )
                return
            if not await is_moderator(client, message, need="can_manage_chat"):
                await denied(
                    ctx,
                    message,
                    "You need Manage chat permission to configure antiflood.",
                )
                return
            args = (message.text or "").split()[1:]
            try:
                if command == "flood" and not args:
                    policy = await read_policy(ctx, message.chat.id)
                elif command == "setflood" and len(args) == 1:
                    value = (
                        0
                        if args[0].lower() in ("off", "no", "0")
                        else int(args[0])
                        if args[0].isascii()
                        and args[0].isdecimal()
                        and len(args[0]) <= 4
                        else -1
                    )
                    policy = await change_policy(
                        ctx, message.chat.id, "consecutive", value, actor=user.id
                    )
                elif (
                    command == "setfloodtimer"
                    and len(args) == 1
                    and args[0].lower() in ("off", "no")
                ):
                    policy = await change_policy(
                        ctx, message.chat.id, "floodtimer", (0, 0), actor=user.id
                    )
                elif (
                    command == "setfloodtimer"
                    and len(args) == 2
                    and args[0].isascii()
                    and args[0].isdecimal()
                    and len(args[0]) <= 4
                ):
                    policy = await change_policy(
                        ctx,
                        message.chat.id,
                        "floodtimer",
                        (int(args[0]), duration(args[1])),
                        actor=user.id,
                    )
                elif command == "floodmode" and 1 <= len(args) <= 2:
                    mode = args[0].lower()
                    if (mode in ("tban", "tmute")) != (len(args) == 2):
                        raise ValueError(
                            "Timed modes require a duration; permanent modes do not."
                        )
                    policy = await change_policy(
                        ctx,
                        message.chat.id,
                        "floodmode",
                        (mode, duration(args[1]) if len(args) == 2 else 0),
                        actor=user.id,
                    )
                elif (
                    command == "clearflood"
                    and len(args) == 1
                    and args[0].lower() in ("yes", "no", "on", "off")
                ):
                    policy = await change_policy(
                        ctx,
                        message.chat.id,
                        "clearflood",
                        args[0].lower() in ("yes", "on"),
                        actor=user.id,
                    )
                else:
                    raise ValueError(
                        "Usage: /flood · /setflood number|off · /setfloodtimer count duration|off · /floodmode ban|mute|kick|tban duration|tmute duration · /clearflood on|off"
                    )
                await reply(
                    message,
                    panel(
                        "Antiflood",
                        table=kv_table(
                            [
                                (
                                    "Consecutive messages",
                                    str(policy.get("consecutive_limit", 0)) or "off",
                                ),
                                (
                                    "Timed messages",
                                    str(policy.get("timed_flood_count", 0)),
                                ),
                                (
                                    "Time window",
                                    f"{policy.get('timed_flood_seconds', 0)}s",
                                ),
                                ("Action", policy.get("flood_action", "mute")),
                                (
                                    "Action duration",
                                    f"{policy.get('flood_action_seconds', 0)}s",
                                ),
                                (
                                    "Delete triggering messages",
                                    "on" if policy.get("clear_flood", True) else "off",
                                ),
                            ]
                        ),
                        note="0 disables a limit. Triggers at the configured count. Counters are process-local and reset on restart; settings are shared through PostgreSQL. Other anti-spam protections remain independent.",
                    ),
                )
            except (ValueError, PolicyError) as error:
                await reply(message, str(error))

        return call

    return {command: handler(command) for command in COMMANDS}


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
