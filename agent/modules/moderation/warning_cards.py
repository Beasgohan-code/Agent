"""Rich base warning and live-authorized, read-only warning summaries."""
import asyncio
import logging
import re
from types import SimpleNamespace
from pyrogram.enums import ChatType,ChatMemberStatus
from pyrogram.types import InlineKeyboardMarkup
from ...platform.warning_policy import operate as read_policy
from ...ui.tables import panel,kv_table,Table
from ...utils.rich import reply

logger=logging.getLogger(__name__)
PREFIX='warnview'


class WarningInputError(ValueError):
    """Locally authored safe validation."""


def personal(user,chat,sender=None):
    return (getattr(chat,'type',None) in (ChatType.GROUP,ChatType.SUPERGROUP)
            and type(getattr(user,'id',None)) is int and 0<user.id<2**63
            and not getattr(user,'is_bot',False) and sender is None)


def build(ctx):
    from . import is_moderator,target_is_protected,escalate_warning
    from .restrictions import target_and_reason
    router=getattr(ctx,'actions',None)

    async def view(client,query,data):
        match=re.fullmatch(r'(-[0-9]{1,19}):([1-9][0-9]{0,18})',data)
        message=getattr(query,'message',None)
        chat=getattr(message,'chat',None)
        actor=getattr(query,'from_user',None)
        if not match or not personal(actor,chat) or int(match[1])!=chat.id or not 0<int(match[2])<2**63:
            await query.answer('Invalid group warning control.',show_alert=True)
            return
        proxy=SimpleNamespace(chat=chat,from_user=actor,sender_chat=None)
        try:
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Current Restrict members permission required to view warning details.',show_alert=True)
                return
            uid=int(match[2])
            rows=await asyncio.wait_for(ctx.chats.awarnings_of(chat.id,uid),10)
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Your administrator permissions changed.',show_alert=True)
                return
            await query.answer('Current warning summary loaded.')
            # Field lengths bound the summary; full retained history stays in canonical storage.
            items=tuple((str(index),str(row.get('reason','No reason'))[:160]) for index,row in enumerate(rows[-3:],max(1,len(rows)-2)))
            await reply(message,panel('Active warnings',icon=ctx.theme.emoji('warn'),
                table=Table(headers=('Warning','Reason (preview)'),rows=items) if items else kv_table([('Active warnings','0')]),
                lines=[f'Member: <code>{uid}</code> · Active warnings: {len(rows)}'],
                note='Read-only group summary, latest 3 reasons (160-character previews). Clearing warnings does not unmute or unban. /rmwarn removes the latest; /resetwarn clears this member’s active warnings.'))
        except Exception as error:
            logger.warning('#Errors Warning summary unavailable (%s)',type(error).__name__)
            await query.answer('Warning summary unavailable. No manual warning change requested.',show_alert=True)
    if router is not None and not router.handles(PREFIX+':x'):
        router.register(PREFIX,view)

    async def warn(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        recorded=False
        try:
            if not personal(user,chat,getattr(message,'sender_chat',None)):
                raise WarningInputError('Use your personal administrator identity in a group.')
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise WarningInputError('Current Restrict members administrator permission required.')
            source=getattr(message,'reply_to_message',None)
            if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                raise WarningInputError('Reply to a member from this group.')
            try:
                uid,reason=await asyncio.wait_for(target_and_reason(client,message),5)
            except ValueError:
                raise WarningInputError('Use /warn @username or positive ID [reason], or reply to a member.') from None
            if type(uid) is not int or not 0<uid<2**63:
                raise WarningInputError('A positive personal target identity is required.')
            me=await asyncio.wait_for(client.get_me(),5)
            if uid in (user.id,me.id):
                raise WarningInputError('Cannot warn yourself or this bot.')
            if await asyncio.wait_for(target_is_protected(client,chat.id,uid),5):
                raise WarningInputError('I cannot act on an administrator or unverified target. Action not attempted.')
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_restrict_members',False)):
                raise WarningInputError('This bot needs Restrict members permission for escalation.')
            policy=await read_policy(ctx.chats,chat.id)
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise WarningInputError('Your administrator permission changed. No warning recorded.')
            reason=reason.strip()[:500] or 'no reason given'
            count=await ctx.chats.aadd_warning(chat.id,uid,moderator_id=user.id,reason=reason)
            recorded=True
            audit=''
            try:
                ctx.chats.log(chat.id,'warn',actor_id=user.id,target_id=uid,reason=reason)
            except Exception:
                logger.warning('#Errors Warning local audit unconfirmed')
                audit=' Local audit unconfirmed.'
            escalation='Threshold not reached.' if policy['limit'] else 'Warning escalation disabled.'
            if policy['limit'] and count>=policy['limit']:
                if await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                    escalation=await escalate_warning(client,ctx,message,uid,policy['action'],confirm=True)
                else:
                    escalation='Warning recorded; escalation not attempted because caller permissions changed.'
            keyboard=InlineKeyboardMarkup([[ctx.theme.button('View warnings',icon='warn',callback_data=f'{PREFIX}:{chat.id}:{uid}')]]) if router is not None else None
            await reply(message,panel('Warning issued',icon=ctx.theme.emoji('warn'),table=kv_table([
                ('Member',str(uid)),('Moderator',str(user.id)),('Active warnings',str(count)),
                ('Threshold',str(policy['limit']) if policy['limit'] else 'off'),('Reason',reason),('Status','Warning recorded')]),
                lines=[escalation],note='View details with /warns '+str(uid)+'. Removing warnings does not undo Telegram restrictions.'+audit),reply_markup=keyboard)
        except WarningInputError as error:
            await reply(message,panel('Warning not applied',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except Exception as error:
            logger.warning('#Errors Warning action unavailable (%s)',type(error).__name__)
            await reply(message,panel('Warning status',icon=ctx.theme.emoji('warn'),lines=[
                'Warning recorded; escalation, audit or result delivery unconfirmed. Inspect /warns and Telegram before any retry. No automatic retry.' if recorded else
                'Warning state or permissions unavailable; recording unconfirmed. Inspect /warns before retrying. No automatic retry.']))
    return warn
