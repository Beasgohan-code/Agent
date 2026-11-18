"""Manual note command: shared target parser, current authority, rich commit status."""
import asyncio
import logging
from pyrogram.enums import ChatType
from ...platform.member_notes import operate,NoteError
from ...ui.tables import panel,kv_table
from ...utils.rich import reply
from .restrictions import target_and_reason

logger=logging.getLogger(__name__)


class NoteInputError(ValueError):
    """Locally authored safe command validation."""


def build(ctx):
    from . import is_moderator

    async def note(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        committed=False
        try:
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise NoteInputError('Use your personal administrator identity inside a group.')
            if not await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5):
                raise NoteInputError('Current Manage chat administrator permission required.')
            source=getattr(message,'reply_to_message',None)
            if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                raise NoteInputError('Reply to a member from this group.')
            try:
                uid,text=await asyncio.wait_for(target_and_reason(client,message),5)
            except ValueError:
                raise NoteInputError('Use /note @username|positive_ID text, or reply /note text.') from None
            if type(uid) is not int or not 0<uid<2**63 or not 1<=len(text.strip())<=2000:
                raise NoteInputError('Provide a personal target and note text of 1–2000 characters.')
            text=text.strip()
            if not await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5):
                raise NoteInputError('Administrator permissions changed. No note saved.')
            result=await operate(ctx.chats,chat.id,uid,body=text,actor=user.id)
            committed=True
            audit=''
            try:
                ctx.chats.log(chat.id,'note',actor_id=user.id,target_id=uid,reason=f'{len(text)} characters; content withheld')
            except Exception:
                logger.warning('#Errors Member note local audit unconfirmed')
                audit=' Local audit unconfirmed.'
            await reply(message,panel('Note saved',icon=ctx.theme.emoji('check'),table=kv_table([
                ('Member',str(uid)),('Moderator',str(user.id)),('Characters',str(len(text))),('Revision',str(result['version']) if result['version'] else 'Standalone'),('Status','Committed')]),
                note='Note body withheld from this confirmation. Authorized admins can inspect its preview with /warns '+str(uid)+'. No warning or Telegram restriction was changed.'+audit))
        except (NoteInputError,NoteError) as error:
            await reply(message,panel('Note status',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except Exception as error:
            logger.warning('#Errors Member note unavailable (%s)',type(error).__name__)
            await reply(message,panel('Note status',icon=ctx.theme.emoji('warn'),lines=[
                'Note committed; result delivery unconfirmed. Inspect /warns before further action.' if committed else
                'Note state or permissions unavailable. Save unconfirmed; no automatic retry.']))
    return note
