"""Typed deletion locks, independently implemented from Miss Rose's docs.

Reference: https://missrose.org/docs/anti-spam/locks/
Only the explicitly listed native message kinds are implemented. No custom
punishments, non-domain allowlists, join/reaction events or warning escalation are implied.
"""
import asyncio
import logging
import re
import ipaddress
from urllib.parse import urlsplit
from weakref import WeakValueDictionary
from pyrogram.enums import ChatType, ChatMemberStatus, MessageEntityType as Entity, MessageOriginType as Origin
from ...ui.tables import panel, Table
from ...utils.rich import reply

COMMANDS = ('lock', 'unlock', 'locks', 'locktypes', 'allowlist', 'rmallowlist', 'rmallowlistall')
TYPES = {
    'audio': 'audio', 'contact': 'contact', 'document': 'document',
    'gif': 'animation', 'location': 'location', 'photo': 'photo',
    'poll': 'poll', 'sticker': 'sticker', 'video': 'video',
    'videonote': 'video_note', 'voice': 'voice', 'game': 'game',
    'emojigame': 'dice', 'album': 'media_group_id', 'inline': 'via_bot',
    'text': 'text',
}
ENTITY_LOCKS = {
    'url': (Entity.URL, Entity.TEXT_LINK),
    'email': (Entity.EMAIL,),
    'phone': (Entity.PHONE_NUMBER,),
    'spoiler': (Entity.SPOILER,),
    'cashtag': (Entity.CASHTAG,),
    'emojicustom': (Entity.CUSTOM_EMOJI,),
    'command': (Entity.BOT_COMMAND,),
}
TYPES.update({kind: None for kind in ENTITY_LOCKS})
TYPES.update({kind: None for kind in ('forward', 'forwarduser', 'forwardbot', 'forwardchannel', 'button', 'stickeranimated', 'stickerpremium')})


def matches(message, kind):
    if kind in ENTITY_LOCKS:
        entities = list(getattr(message, 'entities', None) or []) + list(getattr(message, 'caption_entities', None) or [])
        return any(getattr(entity, 'type', None) in ENTITY_LOCKS[kind] for entity in entities)
    if kind == 'button':
        return bool(button_urls(message))
    if kind in ('forwarduser', 'forwardbot', 'forwardchannel'):
        origin = getattr(message, 'forward_origin', None)
        user = getattr(origin, 'sender_user', None) or getattr(message, 'forward_from', None)
        channel = getattr(origin, 'chat', None) or getattr(origin, 'sender_chat', None) or getattr(message, 'forward_from_chat', None)
        if kind == 'forwardchannel':
            return bool(getattr(channel, 'type', None) == ChatType.CHANNEL)
        if user is not None:
            return getattr(user, 'is_bot', False) is (kind == 'forwardbot')
        return kind == 'forwarduser' and (getattr(origin, 'type', None) == Origin.HIDDEN_USER or bool(getattr(message, 'forward_sender_name', None)))
    if kind == 'forward':
        return any(getattr(message, field, None) is not None for field in (
            'forward_origin', 'forward_date', 'forward_from', 'forward_from_chat', 'forward_sender_name'))
    if kind in ('stickeranimated', 'stickerpremium'):
        sticker = getattr(message, 'sticker', None)
        return bool(sticker and getattr(sticker, 'is_animated' if kind == 'stickeranimated' else 'premium_animation', None))
    return bool(getattr(message, TYPES[kind], None))


ALLOW_KEY = 'content_lock_domains'
KEY = 'typed_content_locks'
_LOCKS = WeakValueDictionary()
logger = logging.getLogger(__name__)


def mutex(ctx, group):
    return _LOCKS.setdefault((id(ctx.chats), group), asyncio.Lock())


def read(ctx, group):
    db = getattr(ctx, 'db', None)
    if ctx.chats is None or (db is not None and not db.connected):
        raise ValueError('Lock storage is unavailable; no change or enforcement confirmed.')
    state = ctx.chats.get(group, KEY, [])
    if not isinstance(state, list) or any(not isinstance(kind, str) or kind not in TYPES for kind in state):
        raise ValueError('Lock settings could not be read safely.')
    return set(state)


def domain(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 253 or any(char.isspace() for char in value):
        raise ValueError('Use domain names only, e.g. /allowlist wikipedia.org. Paths, ports and other allowlist kinds are not implemented.')
    try:
        host = value.rstrip('.').encode('idna').decode('ascii').lower()
        if len(host) > 253 or '.' not in host or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return host
        raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('Use a domain name without paths, credentials, ports or IP addresses.') from None


def button_urls(message):
    keyboard = getattr(getattr(message, 'reply_markup', None), 'inline_keyboard', None) or []
    return [button.url for row in keyboard for button in row if getattr(button, 'url', None)]


def link_allowed(value, domains):
    try:
        if not isinstance(value, str) or len(value) > 8192 or any(char.isspace() for char in value):
            return False
        parts = urlsplit(value if '://' in value else 'https://' + value)
        parts.port
        if parts.scheme not in ('http', 'https') or parts.username is not None or parts.password is not None:
            return False
        host = domain(parts.hostname or '')
        return any(host == item or host.endswith('.' + item) for item in domains)
    except (ValueError, UnicodeError, TypeError):
        return False


def url_allowed(message, domains):
    """Every URL entity must be allowed; unknown/malformed links fail closed."""
    urls = []
    for text_key, entities_key in (('text', 'entities'), ('caption', 'caption_entities')):
        text = getattr(message, text_key, None) or ''
        for entity in getattr(message, entities_key, None) or []:
            kind = getattr(entity, 'type', None)
            if kind not in (Entity.URL, Entity.TEXT_LINK):
                continue
            try:
                if kind == Entity.TEXT_LINK:
                    value = entity.url
                else:
                    offset, length = entity.offset, entity.length
                    if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
                        return False
                    encoded = text.encode('utf-16-le')
                    if (offset + length) * 2 > len(encoded):
                        return False
                    value = encoded[offset*2:(offset+length)*2].decode('utf-16-le')
                if not link_allowed(value, domains):
                    return False
                urls.append(value)
            except (ValueError, UnicodeError, AttributeError, TypeError):
                return False
    return bool(urls)


def read_domains(ctx, group):
    read(ctx, group)  # Same storage availability boundary as lock configuration.
    values = ctx.chats.get(group, ALLOW_KEY, [])
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError('URL allowlist could not be read safely.')
    return {domain(value) for value in values}


async def persist(ctx, group, key, previous, updated):
    try:
        ctx.chats.put(group, key, sorted(updated))
        db = getattr(ctx, 'db', None)
        if db is not None and await db.flush() <= 0:
            raise RuntimeError('unconfirmed write')
    except Exception:
        ctx.chats.put(group, key, sorted(previous))
        raise ValueError('Lock persistence was not confirmed. Previous cached settings retained.') from None


def build(ctx):
    from . import is_moderator
    async def handle(client, message):
        chat, user = getattr(message, 'chat', None), getattr(message, 'from_user', None)
        if (getattr(chat, 'type', None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or type(getattr(user, 'id', None)) is not int or user.id <= 0
                or getattr(message, 'sender_chat', None) is not None):
            await reply(message, 'Use lock commands as yourself in a group.')
            return
        if not await is_moderator(client, message, need='can_delete_messages'):
            await reply(message, 'You need Delete messages administrator permission to manage locks.')
            return
        parts = (getattr(message, 'text', None) or '').lower().split()
        command, args = parts[0].split('@')[0].lstrip('/!.?'), parts[1:]
        try:
            async with mutex(ctx, chat.id):
                current = read(ctx, chat.id)
                if command in ('allowlist', 'rmallowlist', 'rmallowlistall'):
                    previous = read_domains(ctx, chat.id)
                    updated = set(previous)
                    if command == 'rmallowlistall':
                        owner = await client.get_chat_member(chat.id, user.id)
                        if owner.status != ChatMemberStatus.OWNER:
                            raise ValueError('Only the current group owner can clear all domain allowlist entries.')
                        if args != ['confirm']:
                            raise ValueError('This removes every URL-domain exemption. Confirm with /rmallowlistall confirm. Other lock settings are unchanged.')
                        updated = set()
                    elif args:
                        if len(args) > 20:
                            raise ValueError('Edit at most 20 domains per command.')
                        chosen = {domain(value) for value in args}
                        updated = previous | chosen if command == 'allowlist' else previous - chosen
                    elif command == 'rmallowlist':
                        raise ValueError('Use /rmallowlist domain1 [domain2 …].')
                    if len(updated) > 50:
                        raise ValueError('At most 50 domain exemptions per group. Remove some first.')
                    if updated != previous:
                        await persist(ctx, chat.id, ALLOW_KEY, previous, updated)
                    await reply(message, panel('URL lock allowlist', icon=ctx.theme.emoji('shield'),
                        table=Table(headers=('Domain',), rows=tuple((item,) for item in sorted(updated))),
                        lines=[] if updated else ['No domains are exempt.'],
                        note='Domain and subdomains only; every link in a message must be allowed. Exempts URL and URL-button locks only, not other locks or blocklists. Other Rose allowlist kinds and path-specific rules are not implemented.',
                        footer='/allowlist wikipedia.org · /rmallowlist wikipedia.org'))
                    return
                if command in ('lock', 'unlock'):
                    if not args or len(args) > len(TYPES) or any(kind not in TYPES and kind != 'all' for kind in args):
                        raise ValueError('Use /lock or /unlock with supported types. /locktypes lists them. Custom reasons and modes are not implemented.')
                    chosen = set(TYPES) if 'all' in args else set(args)
                    updated = current | chosen if command == 'lock' else current - chosen
                    if updated != current:
                        await persist(ctx, chat.id, KEY, current, updated)
                    current = updated
                elif args and not (command == 'locks' and args == ['list']):
                    raise ValueError('Use /locks, /locks list or /locktypes without other arguments.')
                kinds = sorted(TYPES if command == 'locktypes' or args == ['list'] else current)
                await reply(message, panel('Content locks', icon=ctx.theme.emoji('shield'),
                    table=Table(headers=('Type', 'State'), rows=tuple((kind, 'locked' if kind in current else 'open') for kind in kinds)),
                    lines=[] if kinds else ['No supported content types are locked.'],
                    note='Deletes matching non-admin messages before blocklist handling. Admins are exempt. All means only the supported types listed by /locktypes; no warning or custom punishment.',
                    footer='/lock gif video sticker · /unlock video · /locks list'))
        except ValueError as error:
            await reply(message, str(error))
    return {command: handle for command in COMMANDS}


async def enforce(ctx, client, message):
    chat, user = getattr(message, 'chat', None), getattr(message, 'from_user', None)
    if (getattr(chat, 'type', None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
            or type(getattr(user, 'id', None)) is not int or user.id <= 0
            or getattr(message, 'sender_chat', None) is not None or getattr(message, 'service', None)):
        return False
    async with mutex(ctx, chat.id):
        try:
            kinds = read(ctx, chat.id)
            domains = read_domains(ctx, chat.id) if kinds & {'url', 'button'} else set()
        except ValueError:
            return False
    if 'url' in kinds and url_allowed(message, domains):
        kinds = kinds - {'url'}
    buttons = button_urls(message) if 'button' in kinds else []
    if buttons and all(link_allowed(value, domains) for value in buttons):
        kinds = kinds - {'button'}
    if not any(matches(message, kind) for kind in kinds):
        return False
    try:
        member = await client.get_chat_member(chat.id, user.id)
        if member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            return False
        me = await client.get_me()
        bot = await client.get_chat_member(chat.id, me.id)
        if bot.status != ChatMemberStatus.OWNER and not (bot.status == ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot, 'privileges', None), 'can_delete_messages', False)):
            return True  # Matched lock owns precedence even when bot rights are missing.
        result = await client.delete_messages(chat.id, message.id)
        if result is False:
            logger.warning('Content-lock deletion not acknowledged')
    except Exception:
        logger.warning('Content-lock deletion could not be confirmed')
    return True
