"""Bounded current-group bans. No retries after unconfirmed Telegram effects."""
import asyncio
import logging
from pyrogram.enums import ChatType, ChatMemberStatus as Status
from ...utils.rich import reply

logger = logging.getLogger(__name__)


async def massban(ctx, client, message):
    owner = ctx.settings.owner_id
    user, chat = getattr(message, 'from_user', None), getattr(message, 'chat', None)
    if owner is None or getattr(user, 'id', None) != owner or getattr(message, 'sender_chat', None) is not None:
        await reply(message, 'This command is reserved for the bot owner using a personal identity.')
        return
    if getattr(chat, 'type', None) not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await reply(message, 'Use /massban only in the group where the bans should apply.')
        return
    parts = (getattr(message, 'text', '') or '').split()[1:]
    if not 1 <= len(parts) <= 10 or any(not p.isascii() or not p.isdecimal() or len(p) > 19 or not 0 < int(p) < 2**63 for p in parts):
        await reply(message, 'Usage: <code>/massban ID ID …</code> — 1–10 unique positive user IDs, current group only.')
        return
    ids = [int(p) for p in parts]
    if len(set(ids)) != len(ids):
        await reply(message, 'Duplicate user IDs refused. Submit each target once.')
        return
    confirmed, protected, unconfirmed = 0, 0, 0
    try:
        me = await asyncio.wait_for(client.get_me(), 5)
        if type(getattr(me, 'id', None)) is not int:
            raise ValueError('Bot identity unavailable')
        for uid in ids:
            if ctx.settings.owner_id != owner:
                raise ValueError('Owner changed')
            # Both actors must still have current group ban authority, even the
            # configured Owner. Never substitute global ownership for rights.
            for actor in (owner, me.id):
                member = await asyncio.wait_for(client.get_chat_member(chat.id, actor), 5)
                if member.status != Status.OWNER and not (member.status == Status.ADMINISTRATOR and getattr(getattr(member, 'privileges', None), 'can_restrict_members', False)):
                    raise ValueError('Current ban permission unavailable')
            target = await asyncio.wait_for(client.get_chat_member(chat.id, uid), 5)
            if uid in (owner, me.id) or target.status in (Status.OWNER, Status.ADMINISTRATOR):
                protected += 1
                continue
            if ctx.settings.owner_id != owner:
                raise ValueError('Owner changed')
            result = await asyncio.wait_for(client.ban_chat_member(chat.id, uid), 10)
            if result is not True:
                raise ValueError('Ban acknowledgement unavailable')
            confirmed += 1
            events = getattr(ctx, 'events', None)
            if events is not None:
                events.emit('massban', by=owner, chat_id=chat.id, target_id=uid, outcome='confirmed')
    except Exception as error:
        logger.warning('#Errors Massban stopped (%s)', type(error).__name__)
        unconfirmed = 1
    await reply(message, f'Mass ban: {confirmed} confirmed · {protected} protected · '
                f'{unconfirmed} unconfirmed/stopped. {len(ids) - confirmed - protected} targets not confirmed. '
                'Only this group was targeted. No automatic retries. If stopped, check Telegram membership before a new request.')
