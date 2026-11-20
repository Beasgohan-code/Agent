"""Base ban/unban: live authorization, shared targets, truthful rich results."""
import asyncio
import logging
from pyrogram.enums import ChatType,ChatMemberStatus
from pyrogram.errors import FloodWait
from .restrictions import target_and_reason
from ...ui.tables import panel,kv_table
from ...utils.rich import reply

logger=logging.getLogger(__name__)


class BanInputError(ValueError):
    """Locally authored safe validation."""


def build(ctx):
    from . import is_moderator,target_is_protected

    def handler(command):
        async def call(client,message):
            user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
            attempted=confirmed=False
            try:
                if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise BanInputError('Use your personal administrator identity in a group.')
                if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                    raise BanInputError('Current Restrict members administrator permission required.')
                source=getattr(message,'reply_to_message',None)
                if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                    raise BanInputError('Reply to a member from this group.')
                try:
                    uid,reason=await asyncio.wait_for(target_and_reason(client,message),5)
                except ValueError:
                    raise BanInputError(f'Use /{command} @username or positive ID, or reply to a member.') from None
                if type(uid) is not int or not 0<uid<2**63 or (command=='unban' and reason):
                    raise BanInputError('Use a positive member identity; /unban takes no extra arguments.')
                me=await asyncio.wait_for(client.get_me(),5)
                if uid in (user.id,me.id):
                    raise BanInputError('Cannot change your own or this bot’s membership.')
                if await asyncio.wait_for(target_is_protected(client,chat.id,uid),5):
                    raise BanInputError('I cannot act on an administrator or unverified target. Action not attempted.')
                bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
                if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_restrict_members',False)):
                    raise BanInputError('This bot needs Restrict members administrator permission.')
                if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                    raise BanInputError('Your administrator permission changed. Action not attempted.')
                attempted=True
                result=await asyncio.wait_for(getattr(client,command+'_chat_member')(chat.id,uid),10)
                if result is not True:
                    raise RuntimeError('Membership acknowledgement unavailable')
                confirmed=True
                audit=''
                try:
                    ctx.chats.log(chat.id,command,actor_id=user.id,target_id=uid,reason=reason[:500])
                except Exception:
                    logger.warning('#Errors Ban/unban audit unconfirmed')
                    audit=' Local audit unconfirmed.'
                rows=[('Member',str(uid)),('Moderator',str(user.id)),('Status','Telegram confirmed')]
                if command=='ban':
                    rows.append(('Reason',reason[:500] or 'No reason supplied'))
                await reply(message,panel('Member banned' if command=='ban' else 'Member unbanned',icon=ctx.theme.emoji('lock' if command=='ban' else 'unlock'),table=kv_table(rows),
                    note=('Ban remains until an administrator uses /unban '+str(uid)+'.' if command=='ban' else 'Ban removed; this does not automatically re-add the member to the group.')+audit))
            except BanInputError as error:
                await reply(message,panel('Action not applied',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
            except Exception as error:
                logger.warning('#Errors Ban/unban unavailable (%s)',type(error).__name__)
                wait=f' Telegram asks you to wait {int(error.value)} seconds.' if isinstance(error,FloodWait) else ''
                await reply(message,panel('Moderation status',icon=ctx.theme.emoji('warn'),note=wait or None,lines=[
                    'Telegram confirmed the membership change; result card delivery failed. Inspect member state before further action.' if confirmed else
                    f'Action unconfirmed ({type(error).__name__}). Inspect Telegram before retrying; no automatic retry.' if attempted else
                    'Target or permissions unavailable. Action not attempted.']))
        return call
    return {name:handler(name) for name in ('ban','unban')}
