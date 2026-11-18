"""Paged canonical warning reader with current self/admin access boundaries."""
import asyncio
import html
import logging
import math
import re
from datetime import datetime,timezone
from pyrogram.enums import ChatType,ChatMemberStatus
from pyrogram.types import InlineKeyboardMarkup
from ...platform.member_notes import operate as read_note
from ...platform.warning_policy import operate as read_policy
from ...platform.group_trust import trusted_members
from ...ui.tables import panel,kv_table,Table
from ...utils.rich import reply
from .restrictions import target_and_reason

PREFIX='warnpage'
PAGE_SIZE=3
logger=logging.getLogger(__name__)


class WarningReadError(ValueError):
    """Safe local input/access error."""


def personal(actor,chat,sender=None):
    return (getattr(chat,'type',None) in (ChatType.GROUP,ChatType.SUPERGROUP)
            and type(getattr(actor,'id',None)) is int and 0<actor.id<2**63
            and not getattr(actor,'is_bot',False) and sender is None)


def build(ctx):
    router=getattr(ctx,'actions',None)

    async def access(client,chat,actor,target):
        member=await asyncio.wait_for(client.get_chat_member(chat.id,actor.id),5)
        status=getattr(member,'status',None)
        admin=(status==ChatMemberStatus.OWNER or (status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(member,'privileges',None),'can_restrict_members',False)))
        present=status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.MEMBER) or (status==ChatMemberStatus.RESTRICTED and getattr(member,'is_member',False) is True)
        if not present or (target!=actor.id and not admin):
            raise WarningReadError('Current Restrict members administrator permission required to inspect another member. Members may view their own warnings.')
        return bool(admin)

    async def render(client,chat,actor,target,page):
        admin=await access(client,chat,actor,target)
        rows=await asyncio.wait_for(ctx.chats.awarnings_of(chat.id,target),10)
        policy=await read_policy(ctx.chats,chat.id)
        note=(await read_note(ctx.chats,chat.id,target))['body'] if admin else ''
        approved=target in await trusted_members(ctx,chat.id) if admin else False
        # A revoked admin may not leak another member's details after the reads.
        admin=await access(client,chat,actor,target)
        pages=max(1,math.ceil(len(rows)/PAGE_SIZE))
        if not 1<=page<=pages:
            raise WarningReadError(f'Page unavailable. Current warning history has {pages} page(s); run /warns {target} to refresh.')
        newest=list(reversed(rows))
        records=[]
        for index,row in enumerate(newest[(page-1)*PAGE_SIZE:page*PAGE_SIZE],(page-1)*PAGE_SIZE+1):
            reason=str(row.get('reason','No reason supplied'))
            if len(reason)>500:
                reason=reason[:500]+' [legacy preview]'
            stamp=datetime.fromtimestamp(float(row.get('at',0)),tz=timezone.utc).strftime('%d %b %H:%M UTC')
            records.append((str(index),reason,str(row.get('by') or '-'),stamp))
        lines=[f'Member: <code>{target}</code> · <b>{len(rows)}</b> active warning(s).',f'Page {page} of {pages} · Newest first.']
        if not rows:
            lines.append('No active warnings.')
        if admin and note:
            lines.append('Moderation note (preview, up to 240 characters): '+html.escape(note[:240]))
        if admin and approved:
            lines.append('Approved: yes')
        buttons=[]
        if router is not None:
            if page>1:
                buttons.append(ctx.theme.button('Previous',icon='back',callback_data=f'{PREFIX}:{chat.id}:{target}:{page-1}'))
            if page<pages:
                buttons.append(ctx.theme.button('Next',icon='next',callback_data=f'{PREFIX}:{chat.id}:{target}:{page+1}'))
        keyboard=InlineKeyboardMarkup([buttons]) if buttons else None
        return panel('Warnings',icon=ctx.theme.emoji('warn'),lines=lines,
            table=Table(headers=('#','Reason','By','When'),rows=tuple(records)) if records else kv_table([('Active warnings','0')]),
            note=(f"Escalates at {policy['limit']} warnings ({policy['action']}). " if policy['limit'] else 'Warnings do not escalate in this group. ')+
            'Only active unexpired warnings shown. Page buttons reload current state. /unwarn clears one; /resetwarn clears this member’s active warnings. Neither unbans nor unmutes.'),keyboard

    async def page_press(client,query,data):
        match=re.fullmatch(r'(-[0-9]{1,19}):([1-9][0-9]{0,18}):([1-9][0-9]{0,2})',data)
        message=getattr(query,'message',None)
        chat=getattr(message,'chat',None)
        actor=getattr(query,'from_user',None)
        if not match or not personal(actor,chat) or int(match[1])!=chat.id or not 0<int(match[2])<2**63:
            await query.answer('Invalid group warning page.',show_alert=True)
            return
        try:
            card,keyboard=await render(client,chat,actor,int(match[2]),int(match[3]))
            await query.answer('Current warning page loaded.')
            await reply(message,card,reply_markup=keyboard)
        except WarningReadError as error:
            await query.answer(str(error),show_alert=True)
        except Exception as error:
            logger.warning('#Errors Warning page unavailable (%s)',type(error).__name__)
            await query.answer('Warning page unavailable. No manual warning changes requested.',show_alert=True)
    if router is not None and not router.handles(PREFIX+':x'):
        router.register(PREFIX,page_press)

    async def warnings(client,message):
        actor,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        try:
            if not personal(actor,chat,getattr(message,'sender_chat',None)):
                raise WarningReadError('Use your personal member identity inside a group.')
            args=(getattr(message,'text','') or '').split()[1:]
            source=getattr(message,'reply_to_message',None)
            if not args and source is None:
                target,extra=actor.id,''
            else:
                if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                    raise WarningReadError('Reply to a message from this group.')
                try:
                    target,extra=await asyncio.wait_for(target_and_reason(client,message),5)
                except ValueError:
                    raise WarningReadError('Use /warns @username|positive_ID [page], reply /warns [page], or /warns for yourself.') from None
            if type(target) is not int or not 0<target<2**63 or (extra and not re.fullmatch(r'[1-9][0-9]{0,2}',extra)):
                raise WarningReadError('Use a positive member ID and optional page 1–999.')
            card,keyboard=await render(client,chat,actor,target,int(extra) if extra else 1)
            await reply(message,card,reply_markup=keyboard)
        except WarningReadError as error:
            await reply(message,panel('Warning lookup',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except Exception as error:
            logger.warning('#Errors Warning lookup unavailable (%s)',type(error).__name__)
            await reply(message,panel('Warning lookup unavailable',icon=ctx.theme.emoji('warn'),lines=['Current membership or warning state could not be verified. No manual warning change requested.']))
    return warnings
