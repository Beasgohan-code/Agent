"""Explicit allowlist of group service events; never delete user content."""

import html
import asyncio
import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.service_cleaning import operate, KINDS, CleaningError
from ...utils.rich import reply
from ...ui.tables import panel, kv_table

logger = logging.getLogger(__name__)
SERVICES = {
    "new_chat_members": "joins",
    "left_chat_members": "leaves",
    "left_chat_member": "leaves",
    "pinned_message": "pins",
    "new_chat_title": "title",
    "new_chat_photo": "photo",
    "delete_chat_photo": "photo",
    "video_chat_started": "videochat",
    "video_chat_ended": "videochat",
    "video_chat_scheduled": "videochat",
    "video_chat_members_invited": "videochat",
}
GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


def build(ctx):
    from . import is_moderator

    async def cleanservice(client,message):
        user=getattr(message,'from_user',None)
        committed=False
        async def authorized():
            return await asyncio.wait_for(is_moderator(client,message,need='can_delete_messages'),5)
        try:
            if (getattr(getattr(message,'chat',None),'type',None) not in GROUPS
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                await reply(message,'Use your personal administrator account in a group.')
                return
            if not await authorized():
                await reply(message,'Current Delete messages permission required.')
                return
            args=(getattr(message,'text','') or '').lower().split()[1:]
            if not args:
                kinds=None
            elif args in (['on'],['yes'],['all']):
                kinds=list(KINDS)
            elif args in (['off'],['no'],['none']):
                kinds=[]
            elif len(args)<=len(KINDS) and all(arg in KINDS for arg in args):
                kinds=args
            else:
                await reply(message,'Use /cleanservice on|off or /cleanservice joins leaves pins title photo videochat.')
                return
            if kinds is not None and not await authorized():
                await reply(message,'Administrator permissions changed. No settings changed.')
                return
            state=await operate(ctx,message.chat.id,kinds,actor=user.id if kinds is not None else None)
            committed=kinds is not None
            if not await authorized():
                await reply(message,'Settings saved; permissions changed. Details withheld.' if committed else 'Administrator permissions changed. Settings withheld.')
                return
            labels={'joins':'Join notices','leaves':'Leave notices','pins':'Pin notices',
                'title':'Title changes','photo':'Photo changes','videochat':'Voice chat notices'}
            await reply(message,panel('Service-message cleaning',table=kv_table([
                ('Moderator',str(user.id)),('Status','Saved' if committed else 'Current saved settings'),
                *[(labels[kind],'On' if kind in state else 'Off') for kind in KINDS]]),
                note='/cleanservice on · /cleanservice off\n/cleanservice joins leaves\nReplaces selection. Notices only; pins stay pinned. Needs my Delete messages right.'))
        except CleaningError as error:
            await reply(message,html.escape(str(error)))
        except Exception as error:
            logger.warning('#Errors Service-cleaning settings unavailable (%s)',type(error).__name__)
            await reply(message,'Settings saved; display or permissions unconfirmed. Check /cleanservice.' if committed else 'Settings or permissions unconfirmed. Check /cleanservice before retrying.')

    return {"cleanservice": cleanservice}


async def clean(ctx, client, message):
    if getattr(getattr(message, "chat", None), "type", None) not in GROUPS:
        return False
    service = getattr(message, "service", None)
    kind = SERVICES.get(getattr(service, "value", None))
    if kind is None:
        return False
    try:
        if kind not in await operate(ctx, message.chat.id):
            return False
        me = await client.get_me()
        member = await client.get_chat_member(message.chat.id, me.id)
        if member.status != ChatMemberStatus.OWNER and not (
            member.status == ChatMemberStatus.ADMINISTRATOR
            and getattr(
                getattr(member, "privileges", None), "can_delete_messages", False
            )
        ):
            return False
        confirmed = await client.delete_messages(message.chat.id, message.id)
        if confirmed is not True:
            logger.warning("Service notice deletion unconfirmed; no retry attempted.")
            return False
        return True
    except Exception:
        logger.warning(
            "Service cleaning unavailable or deletion unconfirmed; no retry attempted."
        )
        return False
