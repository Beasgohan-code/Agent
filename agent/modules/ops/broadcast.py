"""Bounded owner broadcast. Database admission precedes every Telegram effect."""
import asyncio
import logging
from pyrogram.enums import ChatType
from ...platform.broadcasts import database, admit, outcome
from ...utils.rich import reply

logger = logging.getLogger(__name__)


async def broadcast(ctx, client, message):
    owner = ctx.settings.owner_id
    if owner is None or getattr(getattr(message, 'from_user', None), 'id', None) != owner or getattr(message, 'sender_chat', None) is not None:
        await reply(message, 'This command is reserved for the bot owner.')
        return
    chat = getattr(message, 'chat', None)
    if getattr(chat, 'type', None) != ChatType.PRIVATE or chat.id != owner:
        await reply(message, 'Broadcasts must be requested in your private chat with this bot.')
        return
    args = (getattr(message, 'text', '') or '').split()[1:]
    source = getattr(message, 'reply_to_message', None)
    if len(args) != 1 or args[0] not in ('-user', '-chat') or source is None:
        await reply(message, 'Reply to a message: <code>/broadcast -user</code> or <code>/broadcast -chat</code>. Maximum 50 known recipients. Pinning and automatic retries are unavailable.')
        return
    if getattr(getattr(source, 'chat', None), 'id', None) != owner or any(getattr(source, key, False) for key in ('empty', 'service', 'has_protected_content')):
        await reply(message, 'Reply to a forwardable message in this private chat. Protected/service messages are not supported.')
        return
    confirmed, stopped = 0, False
    try:
        db = database(ctx)
        # Scoped cached indexes; no user-supplied recipient IDs or global scan.
        index = db.get('users' if args[0] == '-user' else 'chats', {})
        recipients = sorted({int(key) for key in index if isinstance(key, str)
            and len(key) <= 20 and key.removeprefix('-').isascii() and key.removeprefix('-').isdigit()
            and -(2**63) < int(key) < 2**63 and (int(key)>0 if args[0]=='-user' else int(key)<0)})
        if not 1 <= len(recipients) <= 50:
            await reply(message, 'Broadcast requires 1–50 known recipients. None sent; larger audiences need a queued campaign implementation.')
            return
        if not await admit(ctx, message.id, owner, source.id, args[0], recipients):
            await reply(message, 'This request was already admitted. No messages resent; inspect its recorded results before a new request.')
            return
        for recipient in recipients:
            if ctx.settings.owner_id != owner:
                stopped = True
                break
            await outcome(ctx, message.id, recipient, 'sending')
            if ctx.settings.owner_id != owner:
                stopped = True
                break
            try:
                sent = await asyncio.wait_for(client.forward_messages(recipient, owner, source.id), 15)
                destination = getattr(sent, 'id', None)
                if type(destination) is not int or destination <= 0:
                    raise ValueError('Forward acknowledgement unavailable')
            except Exception:
                await outcome(ctx, message.id, recipient, 'unconfirmed')
                raise
            confirmed += 1
            await outcome(ctx, message.id, recipient, 'forwarded', destination)
    except Exception as error:
        logger.warning('#Errors Broadcast stopped (%s)', type(error).__name__)
        stopped = True
    await reply(message, f'Broadcast: {confirmed} Telegram-confirmed forwards. '
                + ('Remaining delivery or outcome persistence unconfirmed; stopped. ' if stopped else 'Delivery outcomes recorded. ')
                + 'No automatic retries. A failed or interrupted campaign may have partial deliveries. Records are scoped to this bot.')
