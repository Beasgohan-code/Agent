"""Short-lived exact-warning removal controls; never remove the latest by accident."""
import asyncio
import logging
import secrets
import time
from collections import OrderedDict
from types import SimpleNamespace
from pyrogram.enums import ChatType
from ...ui.tables import panel,kv_table
from ...utils.rich import reply

PREFIX='warnremove'
logger=logging.getLogger(__name__)


def setup(ctx):
    router=getattr(ctx,'actions',None)
    if router is None:
        return None
    entries=getattr(ctx,'_warning_undo_entries',None)
    if entries is None:
        entries=OrderedDict()
        ctx._warning_undo_entries=entries

    async def remove(client,query,token):
        from . import is_moderator,target_is_protected
        record=entries.get(token)
        message=getattr(query,'message',None)
        chat=getattr(message,'chat',None)
        actor=getattr(query,'from_user',None)
        if (not record or record['expires']<time.monotonic() or getattr(chat,'id',None)!=record['chat']
                or getattr(message,'id',None)!=record.get('message')
                or getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(actor,'id',None)) is not int or not 0<actor.id<2**63
                or getattr(actor,'is_bot',False)):
            await query.answer('Control expired, used or invalid. Use explicit warning commands.',show_alert=True)
            return
        proxy=SimpleNamespace(chat=chat,from_user=actor,sender_chat=None)
        committed=False
        try:
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Current Restrict members permission required.',show_alert=True)
                return
            uid=record['target']
            if await asyncio.wait_for(target_is_protected(client,chat.id,uid),5):
                await query.answer('Member is protected or cannot be verified. No warning removed.',show_alert=True)
                return
            if not await asyncio.wait_for(is_moderator(client,proxy,need='can_restrict_members'),5):
                await query.answer('Your administrator permissions changed. No warning removed.',show_alert=True)
                return
            if entries.pop(token,None) is not record:
                await query.answer('This control has already been used.',show_alert=True)
                return
            # Exact ID comparison and active/expiry test happen under canonical member/group locks.
            removed=await ctx.chats.aclear_warning_id(chat.id,uid,record['warning'],actor_id=actor.id)
            committed=True
            audit=''
            if removed:
                try:
                    ctx.chats.log(chat.id,'warning:remove_exact',actor_id=actor.id,target_id=uid,reason='Specific warning cleared; history retained')
                except Exception:
                    logger.warning('#Errors Exact warning removal local audit unconfirmed')
                    audit=' Local audit unconfirmed.'
            await query.answer('This warning was removed.' if removed else 'Warning already cleared, expired or no longer retained.')
            await reply(message,panel('Warning removed' if removed else 'No warning removed',icon=ctx.theme.emoji('check' if removed else 'info'),
                table=kv_table([('Member',str(uid)),('Moderator',str(actor.id)),('Result','Specific warning cleared' if removed else 'Already cleared, expired or unavailable')]),
                note='Only this card’s warning was targeted. Newer warnings unchanged. History retained; Telegram mute/ban unchanged.'+audit))
        except Exception as error:
            logger.warning('#Errors Exact warning removal unavailable (%s)',type(error).__name__)
            await query.answer('Store operation committed; result delivery failed. Check /warns.' if committed else 'Warning removal unconfirmed. Check /warns before explicit retry; no automatic retry.',show_alert=True)
    if not router.handles(PREFIX+':x'):
        router.register(PREFIX,remove)
    return entries


def issue(ctx,chat,target,warning):
    entries=setup(ctx)
    if entries is None:
        return None,None
    now=time.monotonic()
    for key in list(entries):
        if entries[key]['expires']<now:
            entries.pop(key,None)
    if len(entries)>=200:
        return None,None
    token=secrets.token_urlsafe(16)
    entries[token]=dict(chat=chat,target=target,warning=warning,message=None,expires=now+900)
    return token,ctx.theme.button('Remove this warning',icon='trash',callback_data=PREFIX+':'+token)


def bind(ctx,token,message):
    if token is None:
        return
    entries=ctx._warning_undo_entries
    if type(getattr(message,'id',None)) is int and message.id>0 and token in entries:
        entries[token]['message']=message.id
    else:
        entries.pop(token,None)
