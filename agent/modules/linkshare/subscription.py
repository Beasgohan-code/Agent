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


def build_channels(ctx):
    """Owner-private channel migration surface; legacy file redemption is separate."""
    from datetime import datetime, timedelta, timezone
    from ...platform.channel_shares import ChannelShares, channel_id
    store = ChannelShares(getattr(ctx, 'db', None))

    async def command(client, message):
        actor = getattr(message, 'from_user', None)
        uid = getattr(actor, 'id', None)
        if (type(uid) is not int or not 0 < uid < 2**63 or uid != ctx.settings.owner_id
                or getattr(actor, 'is_bot', False) or getattr(message, 'sender_chat', None) is not None
                or getattr(message.chat, 'type', None) != ChatType.PRIVATE or message.chat.id != uid):
            await reply(message, 'Channel Linkshare management is currently available only to this bot’s Owner in private chat.')
            return
        async def authority(channel):
            if ctx.settings.owner_id != uid:
                raise ValueError('Owner changed')
            chat = await asyncio.wait_for(client.get_chat(channel), API_TIMEOUT)
            if chat.id != channel or chat.type != ChatType.CHANNEL:
                raise ValueError('Channel required')
            for who in (uid, ctx.settings.bot_id):
                member = await asyncio.wait_for(client.get_chat_member(channel, who), API_TIMEOUT)
                if member.status != ChatMemberStatus.OWNER and not (
                        member.status == ChatMemberStatus.ADMINISTRATOR
                        and getattr(getattr(member, 'privileges', None), 'can_invite_users', None) is True):
                    raise ValueError('Invite administrator required')
            if ctx.settings.owner_id != uid:
                raise ValueError('Owner changed')
        args = (getattr(message, 'text', '') or '').split()[1:]
        try:
            if args == ['channels']:
                rows = await store.list()
                if ctx.settings.owner_id != uid:
                    raise ValueError('Owner changed')
                body = '<b>Managed Linkshare channels</b>\n' + '\n'.join(
                    f'<code>{row["channel_id"]}</code> · {"enabled" if row["enabled"] else "disabled"} · {"auto preference" if row["auto_approve"] else "manual"}' for row in rows)
                await reply(message, body + '\nUse /genlink add ID, /genlink mode ID manual|auto, /genlink disable ID, or /genlink ID. Auto mode is a saved preference only until the approval worker is wired.')
                return
            operation = args[0] if args and args[0] in ('add', 'mode', 'disable') else 'invite'
            valid = (operation == 'invite' and len(args) == 1 or operation in ('add', 'disable') and len(args) == 2
                     or operation == 'mode' and len(args) == 3 and args[2] in ('manual', 'auto'))
            raw = args[0] if operation == 'invite' and args else args[1] if len(args) > 1 else ''
            if not valid or not re.fullmatch(r'-[1-9][0-9]{0,18}', raw):
                await reply(message, 'Use /genlink channels, /genlink add -100ID, /genlink mode -100ID manual|auto, /genlink disable -100ID, or /genlink -100ID.')
                return
            channel = int(raw)
            channel_id(channel)
            await authority(channel)
            row = await store.get(channel)
            if operation == 'add':
                await authority(channel)
                await store.configure(channel, actor=uid, enabled=True)
                await reply(message, 'Channel saved. New channels default to manual approval. Use /genlink ID to create temporary invites.')
                return
            if row is None:
                await reply(message, 'Add this channel first with /genlink add ID. No invite was requested.')
                return
            if operation in ('mode', 'disable'):
                await authority(channel)
                await store.configure(channel, actor=uid, **({'auto_approve': args[2] == 'auto'} if operation == 'mode' else {'enabled': False}))
                await reply(message, 'Channel preference saved. The automatic approval worker is not wired yet; request links still need manual approval. Disabling stops new generation but does not revoke existing Telegram invites.')
                return
            if not row['enabled']:
                await reply(message, 'This channel is disabled. No invite was requested.')
                return
            links = []
            for request_mode in (False, True):
                try:
                    await authority(channel)
                    current = await store.get(channel)
                    if ctx.settings.owner_id != uid or not current or not current['enabled']:
                        raise ValueError('Channel disabled')
                    options = {'creates_join_request': True} if request_mode else {'member_limit': 1}
                    result = await asyncio.wait_for(client.create_chat_invite_link(
                        chat_id=channel, expire_date=datetime.now(timezone.utc) + timedelta(minutes=15), **options), 10)
                    url = getattr(result, 'invite_link', None)
                    if not isinstance(url, str) or not re.fullmatch(r'https://t\.me/(?:\+|joinchat/)[A-Za-z0-9_-]+', url):
                        raise ValueError('Invite acknowledgement unavailable')
                    links.append(('Request invite' if request_mode else 'Normal invite', url))
                except Exception:
                    # An ambiguous creation might already have taken effect. Do
                    # not retry it, or proceed to another request after failure.
                    break
            text = '<b>Temporary channel invites</b>\n' + '\n'.join(f'{label}: <code>{html.escape(url)}</code>' for label, url in links)
            text += '\n15-minute expiry. Normal invite: one use. Request invite: manual approval. These are direct Telegram invites, not bot redemption links.'
            if len(links) != 2:
                text += '\nOne or more invite creations were not confirmed. No automatic retry. Inspect channel invites before retrying.'
            await reply(message, text)
        except Exception:
            await reply(message, 'Channel operation was not confirmed. Check storage and current invite permissions for you and this bot; no automatic retry was attempted.')
    return command
