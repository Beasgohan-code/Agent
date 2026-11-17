"""Process-local, short-lived undo controls; callback bytes never confer authority."""
import asyncio
import secrets
import time
from collections import OrderedDict
from types import SimpleNamespace
from pyrogram.enums import ChatType,ChatMemberStatus
from pyrogram.types import InlineKeyboardMarkup
from ...utils.rich import reply
from ...ui.tables import panel,kv_table

PREFIX='muteundo'


def setup(ctx):
    router=getattr(ctx,'actions',None)
    if router is None:
        return None
    entries=getattr(ctx,'_mute_undo_entries',None)
    if entries is None:
        entries=OrderedDict()
        ctx._mute_undo_entries=entries

    async def undo(client,query,token):
        from . import is_moderator,target_is_protected
        record=entries.get(token)
        message=getattr(query,'message',None)
        chat=getattr(message,'chat',None)
        actor=getattr(query,'from_user',None)
        if (not record or record['expires']<time.monotonic() or getattr(chat,'id',None)!=record['chat']
                or getattr(message,'id',None)!=record.get('message')
                or getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(actor,'id',None)) is not int or actor.id<=0 or getattr(actor,'is_bot',False)):
            await query.answer('This control is invalid or expired. Use /unmute explicitly.',show_alert=True)
            return
        proxy=SimpleNamespace(chat=chat,from_user=actor,sender_chat=None)
        attempted=False
        try:
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Current Restrict members permission required.',show_alert=True)
                return
            target=record['target']
            if await asyncio.wait_for(target_is_protected(client,chat.id,target),5):
                await query.answer('Target is protected or cannot be verified.',show_alert=True)
                return
            member=await asyncio.wait_for(client.get_chat_member(chat.id,target),5)
            expiry=getattr(member,'until_date',None)
            if (member.status!=ChatMemberStatus.RESTRICTED or expiry is None
                    or abs(expiry.timestamp()-record['until'])>2):
                await query.answer('Restriction changed or expired. Inspect the member and use /unmute explicitly.',show_alert=True)
                return
            me=await asyncio.wait_for(client.get_me(),5)
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_restrict_members',False)):
                await query.answer('Bot needs Restrict members permission.',show_alert=True)
                return
            group=await asyncio.wait_for(client.get_chat(chat.id),5)
            permissions=getattr(group,'permissions',None)
            if permissions is None:
                await query.answer('Current group permissions unavailable. No change requested.',show_alert=True)
                return
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Your permissions changed. No change requested.',show_alert=True)
                return
            # Consume before network side effect: concurrent/replayed presses cannot reapply.
            if entries.pop(token,None) is not record:
                await query.answer('This action has already been used.',show_alert=True)
                return
            attempted=True
            result=await asyncio.wait_for(client.restrict_chat_member(chat.id,target,permissions),10)
            if result is not True:
                raise RuntimeError('Unmute acknowledgement unavailable')
            audit=''
            try:
                ctx.chats.log(chat.id,'unmute',actor_id=actor.id,target_id=target,reason='Confirmed mute-card undo; current group permissions restored')
            except Exception:
                audit=' Local audit unconfirmed.'
            await query.answer('Unmute confirmed by Telegram.')
            await reply(message,panel('Member unmuted',icon=ctx.theme.emoji('check'),table=kv_table([('Member',str(target)),('By',str(actor.id)),('Status','Telegram confirmed')]),note='Current group permissions restored, not unrestricted rights.'+audit))
        except Exception as error:
            import logging
            logging.getLogger(__name__).warning('#Errors Mute undo unavailable (%s)',type(error).__name__)
            await query.answer('Unmute unconfirmed. Inspect Telegram before using /unmute; no automatic retry.' if attempted else 'Permissions or member state unavailable. No change requested.',show_alert=True)
    if not router.handles(PREFIX+':x'):
        router.register(PREFIX,undo)
    return entries


def issue(ctx,chat,target,until):
    entries=setup(ctx)
    if entries is None:
        return None,None
    now=time.monotonic()
    for key in list(entries):
        if entries[key]['expires']<now or (entries[key]['chat']==chat and entries[key]['target']==target):
            entries.pop(key,None)
    if len(entries)>=200:
        return None,None
    token=secrets.token_urlsafe(16)
    entries[token]=dict(chat=chat,target=target,until=until.timestamp(),expires=now+900,message=None)
    button=ctx.theme.button('Unmute',icon='check',callback_data=PREFIX+':'+token)
    return token,InlineKeyboardMarkup([[button]])


def bind(ctx,token,message):
    if token is None:
        return
    entries=ctx._mute_undo_entries
    if type(getattr(message,'id',None)) is int and message.id>0 and token in entries:
        entries[token]['message']=message.id
    else:
        entries.pop(token,None)
