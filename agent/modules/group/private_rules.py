"""Self-service private delivery, not a group-wide private-rules toggle."""
import asyncio
import html
import logging
from pyrogram.enums import ChatType,ChatMemberStatus
from ...platform import group_rules
from ...ui.tables import panel
from ...utils.rich import reply,send

logger=logging.getLogger(__name__)


def rule_cards(theme,title,text):
    parts=list(group_rules.message_chunks(text))
    for index,part in enumerate(parts):
        escaped='<br/>'.join(html.escape(line) for line in part.splitlines())
        yield panel('Rules',icon=theme.emoji('shield'),subtitle=f'<b>{html.escape(title)}</b>',
            lines=[f'<blockquote>{escaped}</blockquote>'],
            footer=f'Part {index+1} of {len(parts)}' if len(parts)>1 else 'Set by an administrator of this group.')


def build(ctx):
    async def private_rules(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
            await reply(message,'Use your personal member identity inside the group whose rules you want.')
            return
        if len((getattr(message,'text','') or '').split())!=1:
            await reply(message,'Usage: /privaterules in the current group, without arguments. Sends rules to your own DM only.')
            return
        delivered=0
        attempted=False
        try:
            member=await asyncio.wait_for(client.get_chat_member(chat.id,user.id),5)
            if member.status not in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.MEMBER) and not (member.status==ChatMemberStatus.RESTRICTED and getattr(member,'is_member',False) is True):
                await reply(message,'Current group membership could not be verified. No rules sent.')
                return
            text=(await asyncio.wait_for(group_rules.read_rules(ctx,chat.id),5))['body'].strip()
            if not text:
                await reply(message,'This group has no rules stored yet. An administrator can publish them with /setrules.')
                return
            for card in rule_cards(ctx.theme,getattr(chat,'title',None) or 'This group',text):
                attempted=True
                result=await asyncio.wait_for(send(client,user.id,card),10)
                if type(getattr(result,'id',None)) is not int or result.id<=0:
                    raise RuntimeError('DM acknowledgement unavailable')
                delivered+=1
        except Exception as error:
            logger.warning('#Errors Private rules unavailable (%s)',type(error).__name__)
            if attempted:
                await reply(message,f'Private rules delivery unconfirmed ({delivered} parts acknowledged). Open this bot in DM and press Start; check for partial delivery before trying again. No automatic retry and no group fallback.')
            else:
                await reply(message,'Membership or stored rules unavailable. No private rules delivery attempted.')
            return
        await reply(message,'Rules delivered to your DM. No rule contents posted here.')
    return private_rules
