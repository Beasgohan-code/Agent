"""Original bounded archive-copy admission for guided single-message links."""
import asyncio
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.archive_links import database
from .channel_links import private


class IngestError(ValueError):
    """Safe admission message, never raw Telegram/API exception text."""


async def copy_into_archive(ctx, client, message, channel):
    """Copy one private Owner message. A returned ID is not a persisted link."""
    database(ctx)  # Fail before Telegram side effects when durable storage is down.
    owner = ctx.settings.owner_id
    if not private(message) or message.from_user.id != owner:
        raise IngestError('Only this bot’s Owner can archive a message in private chat.')
    if type(channel) is not int or not -(2**63) < channel < 0 or ctx.settings.storage_channel != channel:
        raise IngestError('Archive configuration changed or is unavailable. Start /genlink again.')
    mid = getattr(message, 'id', None)
    if type(mid) is not int or not 0 < mid < 2**31:
        raise IngestError('This message has no usable Telegram message ID.')
    if any(getattr(message, key, False) for key in ('empty', 'service', 'has_protected_content')):
        raise IngestError('Protected, empty or service messages cannot be archived.')
    archive = await asyncio.wait_for(client.get_chat(channel), timeout=10)
    if getattr(archive, 'type', None) != ChatType.CHANNEL or getattr(archive, 'has_protected_content', False):
        raise IngestError('The archive must be a channel without protected content.')
    me = await asyncio.wait_for(client.get_me(), timeout=10)
    if type(getattr(me, 'id', None)) is not int:
        raise IngestError('Bot identity could not be confirmed.')
    for uid in (owner, me.id):
        member = await asyncio.wait_for(client.get_chat_member(channel, uid), timeout=10)
        if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            raise IngestError('Both this bot and its Owner must be archive-channel administrators.')
    if ctx.settings.owner_id != owner or ctx.settings.storage_channel != channel:
        raise IngestError('Archive ownership/configuration changed. No copy requested.')
    database(ctx)
    copied = await asyncio.wait_for(client.copy_message(channel, message.chat.id, mid), timeout=30)
    copied_id = getattr(copied, 'id', None)
    if type(copied_id) is not int or not 0 < copied_id < 2**31:
        raise RuntimeError('Archive copy acknowledgement unavailable')
    if ctx.settings.owner_id != owner or ctx.settings.storage_channel != channel:
        raise IngestError('Configuration changed after copying. No link issued; an archive copy may remain.')
    database(ctx)
    return copied_id
