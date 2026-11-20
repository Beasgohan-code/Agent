"""Bounded silent deletion; Telegram update acknowledgements are not deletion counts."""
import asyncio
import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...utils.rich import reply

logger=logging.getLogger(__name__)


def build(ctx, maximum=100):
    from . import is_moderator

    async def spurge(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(user,'id',None)) is not int or user.id<=0
                or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
            await reply(message,'Use your personal administrator identity in a group.')
            return
        args=(getattr(message,'text','') or '').split()
        raw=args[1] if len(args)==2 else '10'
        base=getattr(message,'id',None)
        if (len(args)>2 or not raw.isascii() or not raw.isdecimal() or len(raw)>3
                or not 1<=int(raw)<=maximum or type(base) is not int or not 1<base<2**31):
            await reply(message,f'Usage: /spurge [count] — 1–{maximum} preceding message IDs, default 10. No reply-based range.')
            return
        ids=list(range(base-1,max(0,base-int(raw)-1),-1))
        attempted=False
        range_ack=False
        try:
            if not await asyncio.wait_for(is_moderator(client,message,need='can_delete_messages'),5):
                await reply(message,'Current Delete messages administrator permission is required.')
                return
            me=await asyncio.wait_for(client.get_me(),5)
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_delete_messages',False)):
                await reply(message,'This bot needs Delete messages administrator permission.')
                return
            if not await asyncio.wait_for(is_moderator(client,message,need='can_delete_messages'),5):
                await reply(message,'Your Delete messages permission changed. No deletion requested.')
                return
            attempted=True
            result=await asyncio.wait_for(client.delete_messages(chat.id,ids),10)
            # Wzgram returns pts_count, NOT an exact count of removed messages.
            if type(result) is not int or result<=0:
                raise RuntimeError('Range deletion acknowledgement unavailable')
            range_ack=True
            try:
                ctx.chats.log(chat.id,'spurge',actor_id=user.id,reason=f'Telegram acknowledged deletion request for {len(ids)} preceding message IDs; exact deletion count unknown')
            except Exception:
                logger.warning('#Errors Silent purge local audit unconfirmed')
                await reply(message,'Range deletion request acknowledged; exact deletion count unknown. Local audit unconfirmed; command retained.')
                return
            # Do not delete the command when range acknowledgement/audit failed.
            result=await asyncio.wait_for(client.delete_messages(chat.id,base),10)
            if type(result) is not int or result<=0:
                raise RuntimeError('Command deletion acknowledgement unavailable')
        except Exception as error:
            logger.warning('#Errors Silent purge unavailable (%s)',type(error).__name__)
            await reply(message,('Range deletion request acknowledged; command cleanup unconfirmed. No automatic retry.' if range_ack else
                                'Deletion unconfirmed; some messages may have been removed. Inspect the group before retrying. No automatic retry.' if attempted else
                                'Permissions unavailable. No deletion requested.'))
    return spurge
