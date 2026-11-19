"""Independent adaptation of LINK-SHAREBOT's pre-delivery membership workflow.

Reviewed plugins/start.py at 265f2acbe720571e7c514cd32eea600292656fe2.
No upstream clients, database implementation or source are imported.
"""
import asyncio
import html
import re
from pyrogram.enums import ChatMemberStatus, ChatType, ButtonStyle
from pyrogram.types import InlineKeyboardMarkup as Keyboard
from ...ui.theme import Theme
from ...utils.rich import reply

DOCUMENT = 'linkshare_subscription'
API_TIMEOUT = 5


def member_allowed(member):
    status = getattr(member, 'status', None)
    return status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER) or (
        status == ChatMemberStatus.RESTRICTED and getattr(member, 'is_member', False) is True)


def channels_for(policy):
    """Read old one-channel documents and new bounded multi-channel policies."""
    if not isinstance(policy, dict):
        raise ValueError('invalid policy')
    channels = policy.get('channels') if 'channels' in policy else ([policy['channel']] if policy.get('channel') is not None else [])
    if (not isinstance(channels, list) or len(channels) > 5
            or any(type(cid) is not int or not -(2**63) < cid < 0 for cid in channels)
            or len(set(channels)) != len(channels)):
        raise ValueError('invalid policy')
    return channels


async def allowed(ctx, client, message):
    db = getattr(ctx, 'db', None)
    if db is None:
        return True
    if not db.connected:
        await reply(message, 'Link access could not be verified while storage is unavailable. No link use was spent.')
        return False
    try:
        channels = channels_for(db.get(DOCUMENT, {}))
    except Exception:
        await reply(message, 'Link access could not be verified. No link use was spent.')
        return False
    if not channels:
        return True
    uid = getattr(getattr(message, 'from_user', None), 'id', None)
    if type(uid) is not int or uid <= 0:
        await reply(message, 'Use your personal Telegram identity to open this link. No link use was spent.')
        return False
    async def is_missing(channel):
        try:
            member = await asyncio.wait_for(client.get_chat_member(channel, uid), timeout=API_TIMEOUT)
            return not member_allowed(member)
        except Exception:
            return True
    results = await asyncio.gather(*(is_missing(channel) for channel in channels))
    missing = [channel for channel, absent in zip(channels, results) if absent]
    if missing:
        async def join_button(channel):
            try:
                chat = await asyncio.wait_for(client.get_chat(channel), timeout=API_TIMEOUT)
                username = getattr(chat, 'username', None)
                if (getattr(chat, 'id', None) == channel and getattr(chat, 'type', None) == ChatType.CHANNEL
                        and isinstance(username, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', username)):
                    theme = getattr(ctx, 'theme', None) or Theme()
                    return theme.button('Join channel', icon='add', url='https://t.me/' + username, style=ButtonStyle.PRIMARY)
            except Exception:
                pass  # Private/inaccessible channels require an Owner-supplied invite.
            return None
        buttons = await asyncio.gather(*(join_button(channel) for channel in missing))
        keyboard = Keyboard([[button] for button in buttons if button is not None]) if any(buttons) else None
        targets = ', '.join(f'<code>{cid}</code>' for cid in missing)
        await reply(message, f'Join the required channels {targets}, then reopen the original link. Ask the bot Owner for invites if needed. Membership could not be confirmed; no link use was spent.',
                    **({'reply_markup': keyboard} if keyboard else {}))
    return not missing


def build(ctx):
    async def configure(client, message):
        uid = getattr(getattr(message, 'from_user', None), 'id', None)
        if type(uid) is not int or uid != ctx.settings.owner_id or getattr(message.chat, 'id', None) != uid:
            await reply(message, 'Only this bot’s Owner may configure /linkchannel in private chat.')
            return
        db = getattr(ctx, 'db', None)
        if db is None or not db.connected:
            await reply(message, 'Database is unavailable. No subscription change confirmed.')
            return
        args = (getattr(message, 'text', None) or '').split()[1:]
        if not args:
            try:
                channels = channels_for(db.get(DOCUMENT, {}))
                display = ', '.join(map(str, channels)) or 'disabled'
            except ValueError:
                display = 'invalid configuration'
            await reply(message, f'Required channels: <code>{html.escape(display)}</code>. Use /linkchannel id1 [id2 … id5] or /linkchannel off. Every channel must be joined. Applies only to this bot’s Linkshare links.')
            return
        if args == ['off']:
            channels = []
        elif (not 1 <= len(args) <= 5 or len(set(args)) != len(args)
              or any(not re.fullmatch(r'-[1-9][0-9]{0,18}', arg) for arg in args)):
            await reply(message, 'Use /linkchannel with 1–5 unique negative channel IDs, or /linkchannel off.')
            return
        else:
            channels = list(map(int, args))
        for channel in channels:
            if channel <= -(2**63):
                await reply(message, 'That channel ID is out of range.')
                return
            try:
                chat = await asyncio.wait_for(client.get_chat(channel), timeout=API_TIMEOUT)
                if chat.type != ChatType.CHANNEL:
                    raise ValueError('channel required')
                for who in (uid, ctx.settings.bot_id):
                    member = await asyncio.wait_for(client.get_chat_member(channel, who), timeout=API_TIMEOUT)
                    if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                        raise ValueError('administrator required')
            except Exception:
                await reply(message, 'Both you and this bot must administer every selected Telegram channel. Configuration was not changed.')
                return
        previous = db.get(DOCUMENT, {})
        try:
            db.save(DOCUMENT, {'channel': channels[0]} if len(channels) == 1 else {'channels': channels})
            if await db.flush() <= 0:
                raise RuntimeError('unconfirmed persistence')
        except Exception:
            try:
                db.save(DOCUMENT, previous)
            except Exception:
                pass  # Storage remains unconfirmed; never report success.
            await reply(message, 'Subscription persistence was not confirmed. Check policy after storage recovers before retrying.')
            return
        await reply(message, 'Required-channel policy saved for this bot. Membership is checked before consuming Linkshare uses; archive-range links are unchanged.')
    return configure
