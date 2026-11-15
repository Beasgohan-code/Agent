"""Typed deletion locks, independently implemented from Miss Rose's docs.

Reference: https://missrose.org/docs/anti-spam/locks/
Only the explicitly listed native message kinds are implemented. No custom
punishments, allowlists, join/reaction events or warning escalation are implied.
"""
import asyncio
import logging
from weakref import WeakValueDictionary
from pyrogram.enums import ChatType, ChatMemberStatus
from ...ui.tables import panel, Table
from ...utils.rich import reply

COMMANDS = ('lock', 'unlock', 'locks', 'locktypes')
TYPES = {
    'audio': 'audio', 'contact': 'contact', 'document': 'document',
    'gif': 'animation', 'location': 'location', 'photo': 'photo',
    'poll': 'poll', 'sticker': 'sticker', 'video': 'video',
    'videonote': 'video_note', 'voice': 'voice', 'game': 'game',
    'emojigame': 'dice', 'album': 'media_group_id', 'inline': 'via_bot',
    'text': 'text',
}
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
                if command in ('lock', 'unlock'):
                    if not args or len(args) > len(TYPES) or any(kind not in TYPES and kind != 'all' for kind in args):
                        raise ValueError('Use /lock or /unlock with supported types. /locktypes lists them. Custom reasons and modes are not implemented.')
                    chosen = set(TYPES) if 'all' in args else set(args)
                    updated = current | chosen if command == 'lock' else current - chosen
                    if updated != current:
                        db = getattr(ctx, 'db', None)
                        try:
                            ctx.chats.put(chat.id, KEY, sorted(updated))
                            if db is not None and await db.flush() <= 0:
                                raise RuntimeError('unconfirmed write')
                        except Exception:
                            ctx.chats.put(chat.id, KEY, sorted(current))
                            raise ValueError('Lock persistence was not confirmed. Previous cached settings retained.') from None
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
        except ValueError:
            return False
    if not any(getattr(message, TYPES[kind], None) for kind in kinds):
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
