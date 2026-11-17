"""Self-service group AFK cards; no activity registry or full-message storage."""
import asyncio
import logging
import re
from pyrogram.enums import ChatType, MessageEntityType
from ...platform.afk import toggle, clear, notice, AFKError
from ...platform.commands import command_name
from ...ui.tables import panel, kv_table
from ...ui.screens import format_uptime
from ...utils.rich import reply

logger=logging.getLogger(__name__)


def personal(message):
    user=getattr(message,'from_user',None)
    return (getattr(getattr(message,'chat',None),'type',None) in (ChatType.GROUP,ChatType.SUPERGROUP)
            and type(getattr(user,'id',None)) is int and user.id>0
            and not getattr(user,'is_bot',False) and getattr(message,'sender_chat',None) is None)


def build(ctx):
    async def afk(client,message):
        if not personal(message):
            await reply(message,'Use your personal identity in a group to toggle your own AFK status.')
            return
        parts=(getattr(message,'text','') or '').split(maxsplit=1)
        reason=parts[1].strip() if len(parts)==2 else 'Away for now'
        if len(reason)>500:
            await reply(message,'AFK reason must be at most 500 characters.')
            return
        try:
            active=await toggle(ctx,message.chat.id,message.from_user.id,message.id,reason)
        except AFKError as error:
            await reply(message,str(error))
            return
        await reply(message,panel('You are now AFK' if active else 'You are back',icon=ctx.theme.emoji('clock' if active else 'check'),
            lines=['Your away card is enabled in this group. The reason is visible to members who ping you.' if active else 'Your AFK status and stored reason were removed in this group.'],
            note='Run /afk again or send a normal non-command message here to clear your status. Only your current AFK status and command replay IDs are stored; no presence or message contents are tracked.'))
    return afk


def watch(ctx):
    async def receive(client,message):
        if not personal(message):
            return
        text=getattr(message,'text',None) or getattr(message,'caption',None) or ''
        if command_name(text) is not None or getattr(message,'service',None):
            return
        try:
            await clear(ctx,message.chat.id,message.from_user.id)
            targets=[]
            replied=getattr(getattr(message,'reply_to_message',None),'from_user',None)
            if replied is not None:
                targets.append(getattr(replied,'id',None))
            entities=getattr(message,'entities',None) or getattr(message,'caption_entities',None) or []
            for entity in entities[:3]:
                if len(targets)>=3:
                    break
                kind=getattr(entity,'type',None)
                if kind==MessageEntityType.TEXT_MENTION:
                    targets.append(getattr(getattr(entity,'user',None),'id',None))
                elif kind==MessageEntityType.MENTION:
                    start,length=getattr(entity,'offset',None),getattr(entity,'length',None)
                    if type(start) is not int or type(length) is not int or start<0 or not 2<=length<=33:
                        continue
                    name=text.encode('utf-16-le')[start*2:(start+length)*2].decode('utf-16-le')
                    if not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',name):
                        continue
                    # Resolve current username ownership instead of persisting a stale username index.
                    try:
                        user=await asyncio.wait_for(client.get_users(name),5)
                        targets.append(getattr(user,'id',None))
                    except Exception as error:
                        logger.warning('#Errors AFK mention lookup unavailable (%s)',type(error).__name__)
            seen=set()
            for uid in targets[:3]:
                if type(uid) is not int or uid<=0 or uid==message.from_user.id or uid in seen:
                    continue
                seen.add(uid)
                state=await notice(ctx,message.chat.id,uid)
                if state is None:
                    continue
                await reply(message,panel('Member is AFK',icon=ctx.theme.emoji('clock'),
                    table=kv_table([('Member',str(uid)),('Away for',format_uptime(max(0,float(state['seconds'])))),('Reason',state['reason'])]),
                    note='Self-set away status for this group, not live presence. Notifications are limited to one per away member every 30 seconds.'))
        except Exception as error:
            # Passive feature failures never flood the chat or expose reason/content.
            logger.warning('#Errors AFK watcher unavailable (%s)',type(error).__name__)
    return receive
