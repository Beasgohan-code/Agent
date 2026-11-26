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
        from ...platform.commands import command_name
        text = getattr(message, 'text', '') or ''
        name = command_name(text)
        parts = text.split()
        args = parts[1:]
        if name == 'settings' and not args:
            args = ['channels']
        try:
            if name == 'batch':
                if (not 1 <= len(args) <= 5 or len(set(args)) != len(args)
                        or any(not re.fullmatch(r'-[1-9][0-9]{0,18}', arg) for arg in args)):
                    await reply(message, 'Use /batch with 1–5 unique managed negative channel IDs. No invites were requested.')
                    return
                channels = list(map(int, args))
                # Validate every target before the first remote side effect.
                for target in channels:
                    channel_id(target)
                    await authority(target)
                    policy = await store.get(target)
                    if not policy or policy.get('enabled') is not True:
                        await reply(message, 'Every batch channel must be registered and enabled. No invites were requested.')
                        return
                from copy import copy
                for target in channels:
                    item = copy(message)
                    item.text = f'/genlink {target}'
                    if await command(client, item) is not True:
                        await reply(message, 'Channel batch stopped after an unconfirmed or refused operation. Confirmed invites above remain valid; inspect channel invites before retrying.')
                        return
                return True
            page = 0
            if len(args) == 2 and args[0] == 'page' and re.fullmatch(r'[0-3]', args[1]):
                page = int(args[1])
                args = ['channels']
            if args == ['channels']:
                rows = await store.list()
                page = min(page, max(0, (len(rows)-1)//5))
                visible = rows[page*5:page*5+5]
                if ctx.settings.owner_id != uid:
                    raise ValueError('Owner changed')
                body = '<b>Managed Linkshare channels</b>\n' + '\n'.join(
                    f'<code>{row["channel_id"]}</code> · {"enabled" if row["enabled"] else "disabled"} · {"auto preference" if row["auto_approve"] else "manual"}' for row in visible)
                await reply(message, body + '\nUse /settings add ID, /settings mode ID manual|auto, /settings disable ID, or /genlink ID. Auto mode approves requests only for enabled, managed channels while Linkshare is active; manual mode leaves approval to administrators.', reply_markup=settings_keyboard(visible, page, len(rows)))
                return
            operation = args[0] if args and args[0] in ('add', 'mode', 'disable', 'invalidate') else 'invite'
            valid = (operation == 'invite' and len(args) == 1 or operation in ('add', 'disable') and len(args) == 2
                     or operation == 'mode' and len(args) == 3 and args[2] in ('manual', 'auto')
                     or operation == 'invalidate' and len(args) == 3 and args[2] == 'confirm')
            raw = args[0] if operation == 'invite' and args else args[1] if len(args) > 1 else ''
            if not valid or not re.fullmatch(r'-[1-9][0-9]{0,18}', raw):
                if name == 'genlink':
                    from ...ui.tables import panel, kv_table
                    await reply(message, panel('Create channel links',
                        lines=['Send <code>/genlink -1001234567890</code> in this private chat.',
                               'Use your managed channel’s actual ID. Add it first with <code>/settings add -1001234567890</code>.'],
                        table=kv_table([('Normal', 'Opens this bot, then offers a one-use channel invite.'),
                                        ('Request', 'Opens this bot, then offers a join-request invite.')]),
                        note='Bot Owner only. You and the bot need channel invite authority. No replied file or expiry/use arguments are accepted.',
                        footer='No bot links or Telegram invites were created.'))
                else:
                    await reply(message, 'Use /settings, /settings add -100ID, /settings mode -100ID manual|auto, /settings disable -100ID, or /genlink -100ID.')
                return
            channel = int(raw)
            channel_id(channel)
            await authority(channel)
            row = await store.get(channel)
            if operation == 'add':
                await authority(channel)
                await store.configure(channel, actor=uid, enabled=True)
                await reply(message, 'Channel saved. New channels default to manual approval. Use /genlink ID to create normal and request bot links.')
                return
            if row is None:
                await reply(message, 'Add this channel first with /settings add ID. No invite was requested.')
                return
            if operation == 'invalidate':
                await authority(channel)
                count = await store.invalidate(channel)
                await reply(message, f'{count} bot links revoked for this channel. Previously issued Telegram invites and delivered copies are not revoked. New links may be generated separately.')
                return
            if operation in ('mode', 'disable'):
                await authority(channel)
                await store.configure(channel, actor=uid, **({'auto_approve': args[2] == 'auto'} if operation == 'mode' else {'enabled': False}))
                await reply(message, 'Channel preference saved. Auto mode approves join requests only while this channel is enabled and both the Owner and bot retain invite authority. Manual mode leaves requests for administrators. Disabling stops generation and automatic approval but does not revoke existing Telegram invites.')
                return
            if row.get('enabled') is not True:
                await reply(message, 'This channel is disabled. No invite was requested.')
                return
            from ...ui.bot_identity import bot_username
            username = await bot_username(client)
            if not username:
                await reply(message, 'Bot username is unavailable. No bot link was created.')
                return
            tokens = await store.issue(channel)
            from ...ui.tables import panel, kv_table
            from ...ui.tables import markup
            rows = [('Channel', str(channel))]
            for mode, token in tokens.items():
                url = f'https://t.me/{username}?start=channel_{token}'
                rows.append((mode.title(), markup(f'<a href="{url}">{html.escape(url)}</a>')))
            await reply(message, panel('Channel bot links', table=kv_table(rows),
                lines=['<b>Normal</b> offers a one-use invite. <b>Request</b> offers a join-request invite; current manual/auto policy decides approval.'],
                note='Valid for 30 days while the channel is enabled. Opening a link rechecks current access before requesting a 15-minute invite. These bot links can be shared and reused; keep them private.',
                footer='No Telegram invite was created yet. Manage or revoke bot links in /settings.'))
            return True
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


async def redeem_channel(ctx, client, message, token):
    """Resolve an opaque stored bot link, then request one temporary invite."""
    from datetime import datetime, timedelta, timezone
    from ...platform.channel_shares import ChannelShares, personal_id
    user = getattr(message, 'from_user', None)
    uid = getattr(user, 'id', None)
    if (not personal_id(uid) or getattr(user, 'is_bot', False)
            or getattr(message, 'sender_chat', None) is not None
            or getattr(getattr(message, 'chat', None), 'type', None) != ChatType.PRIVATE
            or message.chat.id != uid):
        await reply(message, 'Open this channel link in a private chat using your personal Telegram account.')
        return
    try:
        store = ChannelShares(getattr(ctx, 'db', None))
        grant = await store.resolve(token)
        if not grant:
            await reply(message, 'This channel link is invalid, expired or disabled.')
            return
        if not await allowed(ctx, client, message):
            return
        channel = grant['channel_id']
        owner, bot = ctx.settings.owner_id, ctx.settings.bot_id
        if not personal_id(owner) or not personal_id(bot):
            raise ValueError('Identity unavailable')
        chat = await asyncio.wait_for(client.get_chat(channel), API_TIMEOUT)
        if chat.id != channel or chat.type != ChatType.CHANNEL:
            raise ValueError('Channel unavailable')
        for who in (owner, bot):
            member = await asyncio.wait_for(client.get_chat_member(channel, who), API_TIMEOUT)
            if member.status != ChatMemberStatus.OWNER and not (
                    member.status == ChatMemberStatus.ADMINISTRATOR
                    and getattr(getattr(member, 'privileges', None), 'can_invite_users', None) is True):
                raise ValueError('Invite authority unavailable')
        if await store.resolve(token) != grant or (ctx.settings.owner_id, ctx.settings.bot_id) != (owner, bot):
            raise ValueError('Policy changed')
        options = {'creates_join_request': True} if grant['request_mode'] else {'member_limit': 1}
        result = await asyncio.wait_for(client.create_chat_invite_link(
            chat_id=channel, expire_date=datetime.now(timezone.utc) + timedelta(minutes=15), **options), 10)
        url = getattr(result, 'invite_link', None)
        if not isinstance(url, str) or not re.fullmatch(r'https://t\.me/(?:\+|joinchat/)[A-Za-z0-9_-]+', url):
            raise ValueError('Invite acknowledgement unavailable')
        await reply(message, f'<b>Channel invite</b>\n<code>{html.escape(url)}</code>\nExpires in 15 minutes. '
                    + ('Request approval follows the channel’s current manual/auto policy.' if grant['request_mode'] else 'This normal invite permits one join.'))
    except Exception as error:
        import logging
        logging.getLogger(__name__).warning('#Errors Channel bot-link delivery unconfirmed (%s); no retry', type(error).__name__)
        await reply(message, 'Channel invite creation was not confirmed. No automatic retry. Contact the bot Owner to inspect channel invites before retrying.')


def settings_keyboard(rows, page, total):
    from pyrogram.types import InlineKeyboardButton as Button
    buttons = []
    for row in rows:
        cid = row['channel_id']
        buttons.append([Button(f'{cid} · Generate links', callback_data=f'chset:genlink:{cid}')])
        buttons.append([Button('Manual ✓' if row['auto_approve'] is False else 'Manual', callback_data=f'chset:mode:{cid}:manual'),
                        Button('Auto ✓' if row['auto_approve'] is True else 'Auto', callback_data=f'chset:mode:{cid}:auto'),
                        Button('Disable' if row['enabled'] else 'Enable', callback_data=f'chset:{"disable" if row["enabled"] else "enable"}:{cid}')])
        buttons.append([Button('Revoke bot links…', callback_data=f'chset:revokeask:{cid}')])
    nav = []
    if page > 0:
        nav.append(Button('Previous', callback_data=f'chset:page:{page-1}'))
    nav.append(Button('Refresh', callback_data=f'chset:page:{page}'))
    if (page+1)*5 < total:
        nav.append(Button('Next', callback_data=f'chset:page:{page+1}'))
    buttons.append(nav)
    return Keyboard(buttons)


def build_controls(ctx):
    """Do not trust callback-origin sender or stale displayed policy."""
    from copy import copy
    import secrets
    import time
    from pyrogram.types import InlineKeyboardButton as Button
    pending = {}

    async def press(client, query, rest):
        uid = getattr(getattr(query, 'from_user', None), 'id', None)
        message = getattr(query, 'message', None)
        if (type(uid) is not int or uid != ctx.settings.owner_id
                or getattr(getattr(message, 'chat', None), 'type', None) != ChatType.PRIVATE
                or message.chat.id != uid or getattr(query.from_user, 'is_bot', False)):
            await query.answer('Only this bot’s Owner may use private channel settings.', show_alert=True)
            return
        parts = rest.split(':') if isinstance(rest, str) else []
        action = parts[0] if parts else ''
        if action == 'page' and len(parts) == 2 and re.fullmatch(r'[0-3]', parts[1]):
            text = '/settings page ' + parts[1]
        elif action == 'confirm' and len(parts) == 2:
            entry = pending.pop(parts[1], None)
            if entry is None or entry[1] <= time.monotonic():
                await query.answer('This confirmation expired or was already used. Reopen /settings.', show_alert=True)
                return
            text = f'/settings invalidate {entry[0]} confirm'
        elif (action in ('genlink', 'enable', 'disable', 'mode', 'revokeask')
              and len(parts) == (3 if action == 'mode' else 2)
              and re.fullmatch(r'-[1-9][0-9]{0,18}', parts[1])
              and (action != 'mode' or parts[2] in ('manual', 'auto'))):
            cid = parts[1]
            if action == 'revokeask':
                now = time.monotonic()
                for key in list(pending):
                    if pending[key][1] <= now:
                        pending.pop(key, None)
                if len(pending) >= 20:
                    pending.pop(next(iter(pending)))
                nonce = secrets.token_urlsafe(9)
                pending[nonce] = (cid, now + 120)
                await query.answer()
                await reply(message, 'Revoke all existing bot links for this channel? This cannot revoke already issued Telegram invites. Concurrently generated new links may remain valid.',
                            reply_markup=Keyboard([[Button('Confirm revoke bot links', callback_data=f'chset:confirm:{nonce}'),
                                                    Button('Cancel', callback_data='chset:page:0')]]))
                return
            text = (f'/genlink {cid}' if action == 'genlink' else
                    f'/settings {"add" if action == "enable" else action} {cid}' + (f' {parts[2]}' if action == 'mode' else ''))
        else:
            await query.answer('This settings button is invalid. Reopen /settings.', show_alert=True)
            return
        await query.answer()
        request = copy(message)
        request.text = text
        request.from_user = query.from_user
        return await build_channels(ctx)(client, request)

    async def guarded(client, query, rest):
        gate = getattr(ctx, 'plugin_gate', None)
        if gate is None:
            await query.answer('Channel settings runtime is unavailable.', show_alert=True)
            return
        return await gate.wrap('linkshare', press, callback=True)(client, query, rest)
    return guarded
