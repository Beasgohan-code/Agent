"""Explicit owner-only group delegation, capped by the bot's current rights."""
import asyncio
import logging
import secrets
import time
from types import SimpleNamespace
from pyrogram.types import InlineKeyboardMarkup,InlineKeyboardButton
from ...platform.commands import replied_message,ReplyTargetError
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.types import ChatPrivileges
from .admin import RIGHTS
from ...utils.rich import reply

logger=logging.getLogger(__name__)
# Channel-only posting/editing/direct-message permissions are never delegated here.
GROUP_RIGHTS=(*RIGHTS,'can_promote_members','can_manage_topics','can_post_stories','can_edit_stories','can_delete_stories','can_manage_tags','can_manage_linked_peers','can_send_welcome_messages')


class InputError(ValueError):
    """Locally authored safe validation."""


def build(ctx):
    pending={}
    router=getattr(ctx,'actions',None)

    def prune():
        now=time.monotonic()
        for token,item in list(pending.items()):
            if item['until']<=now:
                pending.pop(token,None)

    async def preview(message,user,uid):
        prune()
        if len(pending)>=128:
            raise InputError('Too many pending confirmations. Wait two minutes and try again.')
        text=(f'Selected member: <code>{uid}</code>. Confirm full promotion? This can grant Add administrators and delegation rights, capped by my rights. '
              'Use /promote for limited rights. No promotion has been requested.')
        if router is None:
            await reply(message,text+f' Confirm with <code>/fullpromote {uid} confirm</code>.')
            return
        token=secrets.token_hex(12)
        keyboard=InlineKeyboardMarkup([
            [InlineKeyboardButton('Confirm full promotion',callback_data=f'fullpromote:{token}:confirm')],
            [InlineKeyboardButton('Cancel',callback_data=f'fullpromote:{token}:cancel')],
        ])
        sent=await asyncio.wait_for(reply(message,text,reply_markup=keyboard),10)
        mid=getattr(sent,'id',None)
        if type(mid) is not int or mid<=0:
            raise InputError(f'Confirmation card unconfirmed. No promotion requested. Use /fullpromote {uid} confirm explicitly.')
        pending[token]={'chat':message.chat.id,'actor':user.id,'target':uid,'message':mid,'until':time.monotonic()+120}

    async def fullpromote(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
            await reply(message,'Use your personal group owner identity inside a group.')
            return
        attempted=False
        try:
            args=(getattr(message,'text','') or '').split()[1:]
            replied=await replied_message(client,message)
            if replied is not None:
                if args not in ([],['confirm']) or getattr(getattr(replied,'chat',None),'id',chat.id)!=chat.id:
                    raise InputError('Reply to a member in this group with /fullpromote confirm. Grants delegation rights; use /promote for limited rights.')
                if getattr(replied,'sender_chat',None) is not None:
                    raise InputError('Reply to a personal member message, not an anonymous sender or channel.')
                target=getattr(replied,'from_user',None)
                needs_confirmation=not args
            else:
                if len(args) not in (1,2) or len(args)==2 and args[1]!='confirm':
                    raise InputError('Usage: /fullpromote @username|positive_ID confirm. Grants delegation rights; use /promote for limited rights.')
                needs_confirmation=len(args)==1
                value=args[0]
                import re
                if value.isascii() and value.isdecimal() and len(value)<=19 and 0<int(value)<2**63:
                    value=int(value)
                elif not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',value):
                    raise InputError('Use a positive user ID or @username followed by confirm.')
                target=None
            caller=await asyncio.wait_for(client.get_chat_member(chat.id,user.id),5)
            if caller.status!=ChatMemberStatus.OWNER:
                raise InputError('Only the current Telegram group owner may use fullpromote.')
            if replied is None:
                target=await asyncio.wait_for(client.get_users(value),5)
            uid=getattr(target,'id',None)
            if type(uid) is not int or not 0<uid<2**63:
                raise InputError('A personal target identity is required.')
            if uid==user.id:
                raise InputError('Cannot change your own privileges.')
            if needs_confirmation:
                await preview(message,user,uid)
                return
            me=await asyncio.wait_for(client.get_me(),5)
            if uid in (user.id,me.id):
                raise InputError('Cannot change your own or this bot’s privileges.')
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            privileges=getattr(bot,'privileges',None)
            if bot.status!=ChatMemberStatus.ADMINISTRATOR or not getattr(privileges,'can_promote_members',False):
                raise InputError('This bot needs Add administrators permission.')
            member=await asyncio.wait_for(client.get_chat_member(chat.id,uid),5)
            if member.status!=ChatMemberStatus.MEMBER:
                raise InputError('Target must be an unrestricted current member, not an existing administrator. No rights overwritten.')
            final=await asyncio.wait_for(client.get_chat_member(chat.id,user.id),5)
            if final.status!=ChatMemberStatus.OWNER:
                raise InputError('Group ownership changed. No promotion requested.')
            delegated=ChatPrivileges(**{right:bool(getattr(privileges,right,False)) for right in GROUP_RIGHTS},is_anonymous=False,can_post_messages=False,can_edit_messages=False,can_manage_direct_messages=False)
            attempted=True
            result=await asyncio.wait_for(client.promote_chat_member(chat.id,uid,privileges=delegated),10)
            if result is not True:
                raise RuntimeError('Promotion acknowledgement unavailable')
            try:
                ctx.chats.log(chat.id,'fullpromote',actor_id=user.id,target_id=uid,reason='Owner-confirmed group delegation capped by bot rights')
            except Exception:
                logger.warning('#Errors Full promotion local audit unconfirmed')
                await reply(message,'Promotion confirmed by Telegram; local audit unconfirmed. Inspect /rights for current permissions.')
                return
            await reply(message,f'Promotion confirmed by Telegram for <code>{uid}</code>. Group rights capped by this bot’s snapshot, including Add administrators. Anonymous identity and channel-only rights excluded. Use /rights to inspect current rights.')
        except (InputError,ReplyTargetError) as error:
            await reply(message,str(error))
        except Exception as error:
            logger.warning('#Errors Full promotion unavailable (%s)',type(error).__name__)
            await reply(message,'Promotion unconfirmed. Inspect /rights before retrying; no automatic retry.' if attempted else 'Group permissions or target unavailable. No promotion requested.')
    async def press(client,query,rest):
        prune()
        bits=rest.split(':')
        item=pending.get(bits[0]) if len(bits)==2 else None
        if item is None or bits[1] not in ('confirm','cancel'):
            await query.answer('Confirmation expired or already used. Run /fullpromote again.',show_alert=True)
            return
        actor=getattr(query,'from_user',None)
        card=getattr(query,'message',None)
        if (getattr(actor,'id',None)!=item['actor'] or getattr(actor,'is_bot',False)
                or getattr(getattr(card,'chat',None),'id',None)!=item['chat'] or getattr(card,'id',None)!=item['message']):
            await query.answer('Use your own confirmation in the original group.',show_alert=True)
            return
        pending.pop(bits[0],None)
        if bits[1]=='cancel':
            await query.answer('Cancelled. No promotion requested.')
            return
        await query.answer('Checking current ownership and permissions.')
        command=SimpleNamespace(text=f"/fullpromote {item['target']} confirm",from_user=actor,
            chat=card.chat,id=card.id,sender_chat=None,reply_to_message=None,
            reply=card.reply,_client=getattr(card,'_client',None))
        await fullpromote(client,command)

    if router is not None and not router.handles('fullpromote:x'):
        router.register('fullpromote',press)
    return fullpromote
