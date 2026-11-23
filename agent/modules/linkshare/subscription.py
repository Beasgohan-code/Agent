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
        parts = (getattr(message, 'text', '') or '').split()
        args = parts[1:]
        if parts and parts[0].split('@', 1)[0].lstrip('/') == 'settings' and not args:
            args = ['channels']
        try:
            if args == ['channels']:
                rows = await store.list()
                if ctx.settings.owner_id != uid:
                    raise ValueError('Owner changed')
                body = '<b>Managed Linkshare channels</b>\n' + '\n'.join(
                    f'<code>{row["channel_id"]}</code> · {"enabled" if row["enabled"] else "disabled"} · {"auto preference" if row["auto_approve"] else "manual"}' for row in rows)
                await reply(message, body + '\nUse /settings add ID, /settings mode ID manual|auto, /settings disable ID, or /genlink ID. Auto mode approves requests only for enabled, managed channels while Linkshare is active; manual mode leaves approval to administrators.')
                return
            operation = args[0] if args and args[0] in ('add', 'mode', 'disable') else 'invite'
            valid = (operation == 'invite' and len(args) == 1 or operation in ('add', 'disable') and len(args) == 2
                     or operation == 'mode' and len(args) == 3 and args[2] in ('manual', 'auto'))
            raw = args[0] if operation == 'invite' and args else args[1] if len(args) > 1 else ''
            if not valid or not re.fullmatch(r'-[1-9][0-9]{0,18}', raw):
                await reply(message, 'Use /settings, /settings add -100ID, /settings mode -100ID manual|auto, /settings disable -100ID, or /genlink -100ID.')
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
                await reply(message, 'Add this channel first with /settings add ID. No invite was requested.')
                return
            if operation in ('mode', 'disable'):
                await authority(channel)
                await store.configure(channel, actor=uid, **({'auto_approve': args[2] == 'auto'} if operation == 'mode' else {'enabled': False}))
                await reply(message, 'Channel preference saved. Auto mode approves join requests only while this channel is enabled and both the Owner and bot retain invite authority. Manual mode leaves requests for administrators. Disabling stops generation and automatic approval but does not revoke existing Telegram invites.')
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
            text += '\n15-minute expiry. Normal invite: one use. Request approval follows this channel’s current manual/auto policy while Linkshare is active. These are direct Telegram invites, not bot redemption links.'
            if len(links) != 2:
                text += '\nOne or more invite creations were not confirmed. No automatic retry. Inspect channel invites before retrying.'
            await reply(message, text)
        except Exception:
            await reply(message, 'Channel operation was not confirmed. Check storage and current invite permissions for you and this bot; no automatic retry was attempted.')
    return command


async def approve_request(ctx, client, update):
    """Opt-in channel approval only; no global approval, retry or unsolicited DM."""
    import logging
    from ...platform.channel_shares import ChannelShares, personal_id, channel_id
    try:
        # Native guard queries belong exclusively to Security's human-review
        # path. Never let an opt-in channel policy bypass that decision.
        if getattr(update, 'query_id', None):
            return
        user = getattr(update, 'from_user', None)
        uid = getattr(user, 'id', None)
        channel = getattr(getattr(update, 'chat', None), 'id', None)
        if not personal_id(uid) or getattr(user, 'is_bot', False):
            return
        channel_id(channel)
        if getattr(update.chat, 'type', None) != ChatType.CHANNEL:
            return
        store = ChannelShares(getattr(ctx, 'db', None))
        row = await store.get(channel)
        def automatic(value):
            return isinstance(value, dict) and value.get('enabled') is True and value.get('auto_approve') is True
        if not automatic(row):
            return
        owner = ctx.settings.owner_id
        bot = ctx.settings.bot_id
        if not personal_id(owner) or not personal_id(bot):
            return
        chat = await asyncio.wait_for(client.get_chat(channel), API_TIMEOUT)
        if chat.id != channel or chat.type != ChatType.CHANNEL:
            return
        for who in (owner, bot):
            member = await asyncio.wait_for(client.get_chat_member(channel, who), API_TIMEOUT)
            if member.status != ChatMemberStatus.OWNER and not (
                    member.status == ChatMemberStatus.ADMINISTRATOR
                    and getattr(getattr(member, 'privileges', None), 'can_invite_users', None) is True):
                return
        # Read through storage again immediately before the remote effect. There
        # is no atomic transaction spanning Telegram and local policy changes.
        if not automatic(await store.get(channel)) or ctx.settings.owner_id != owner or ctx.settings.bot_id != bot:
            return
        result = await asyncio.wait_for(client.approve_chat_join_request(channel, uid), API_TIMEOUT)
        if result is not True:
            logging.getLogger(__name__).warning('#Errors Channel join approval acknowledgement unavailable; no retry')
    except Exception as error:
        logging.getLogger(__name__).warning('#Errors Channel join approval unconfirmed (%s); no retry', type(error).__name__)
