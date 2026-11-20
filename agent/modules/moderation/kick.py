"""Rich base kick with shared two-step recovery, never a fictional undo/re-add button."""
import asyncio
import logging
from pyrogram.enums import ChatType,ChatMemberStatus
from pyrogram.errors import FloodWait
from .restrictions import target_and_reason
from ...ui.tables import panel,kv_table
from ...utils.rich import reply

logger=logging.getLogger(__name__)


class KickInputError(ValueError):
    """Locally authored validation, safe to show."""


def build(ctx):
    from . import is_moderator,target_is_protected,kick_member,PartialKickError

    async def kick(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        attempted=confirmed=False
        try:
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise KickInputError('Use your personal administrator identity in a group.')
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise KickInputError('Current Restrict members administrator permission required.')
            source=getattr(message,'reply_to_message',None)
            if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                raise KickInputError('Reply to a member from this group.')
            try:
                uid,reason=await asyncio.wait_for(target_and_reason(client,message),5)
            except ValueError:
                raise KickInputError('Use /kick @username or positive ID [reason], or reply to a member.') from None
            if type(uid) is not int or not 0<uid<2**63:
                raise KickInputError('A positive personal target identity is required.')
            me=await asyncio.wait_for(client.get_me(),5)
            if uid in (user.id,me.id):
                raise KickInputError('Cannot kick yourself or this bot; use /kickme to leave voluntarily.')
            if await asyncio.wait_for(target_is_protected(client,chat.id,uid),5):
                raise KickInputError('I cannot act on an administrator or unverified target. Action not attempted.')
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_restrict_members',False)):
                raise KickInputError('This bot needs Restrict members administrator permission.')
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise KickInputError('Your administrator permission changed. Action not attempted.')
            attempted=True
            await kick_member(client,ctx,chat.id,uid,actor_id=user.id,source='manual',confirm=True)
            confirmed=True
            audit=''
            try:
                ctx.chats.log(chat.id,'kick',actor_id=user.id,target_id=uid,reason=reason[:500])
            except Exception:
                logger.warning('#Errors Kick local audit unconfirmed')
                audit=' Local audit unconfirmed.'
            await reply(message,panel('Member kicked',icon=ctx.theme.emoji('shield'),table=kv_table([
                ('Member',str(uid)),('Moderator',str(user.id)),('Reason',reason[:500] or 'No reason supplied'),('Status','Telegram confirmed ban and unban')]),
                note='Member removed, not left banned. They may rejoin if group access permits; bots cannot silently add them back.'+audit))
        except KickInputError as error:
            await reply(message,panel('Kick not applied',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except PartialKickError as error:
            # Shared helper creates this safe recovery text, never raw provider text.
            await reply(message,panel('Kick incomplete',icon=ctx.theme.emoji('warn'),lines=[str(error)],note='No automatic retry. Inspect the member before explicit recovery.'))
        except Exception as error:
            logger.warning('#Errors Kick unavailable (%s)',type(error).__name__)
            wait=f' Wait {int(error.value)} seconds.' if isinstance(error,FloodWait) else ''
            await reply(message,panel('Kick status',icon=ctx.theme.emoji('warn'),lines=[
                'Telegram confirmed kick; result card delivery failed. Inspect member state before further action.' if confirmed else
                f'Kick unconfirmed ({type(error).__name__}). Inspect Telegram before retrying; no automatic retry.'+wait if attempted else
                'Target or permissions unavailable. Action not attempted.']))
    return kick
