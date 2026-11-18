"""Recent audit-window reader; source outcomes are not Telegram state proof."""
import asyncio
import logging
import math
import time
from pyrogram.enums import ChatType
from ...platform.antispam import policy_history
from ...platform.group_rules import rules_history
from ...platform.group_trust import trust_history
from ...platform.restriction_cases import history as restriction_history
from ...platform.blocklists import history as blocklist_history
from ...ui.tables import panel,Table
from ...utils.rich import reply

logger=logging.getLogger(__name__)


class LogInputError(ValueError):
    """Safe locally authored reader validation."""


def clip(value,limit):
    text=' '.join(str(value or '-').split())
    return text if len(text)<=limit else text[:limit]+'…'


def timestamp(row):
    value=float(row.get('at',0))
    if not math.isfinite(value) or not 0<=value<=253402300799:
        raise ValueError('Invalid audit timestamp')
    return value


def build(ctx):
    from . import is_moderator

    async def modlog(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        async def authorized():
            return await asyncio.wait_for(is_moderator(client,message),5)
        try:
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise LogInputError('Use your personal administrator identity inside a group.')
            if not await authorized():
                raise LogInputError('Current group administrator permission required.')
            args=(getattr(message,'text','') or '').split()[1:]
            if (len(args)>1 or args and (not args[0].isascii() or not args[0].isdecimal() or len(args[0])>2 or not 1<=int(args[0])<=4)):
                raise LogInputError('Usage: /modlog [page 1–4]')
            page=int(args[0]) if args else 1
            rows=[(dict(row),'Local audit') for row in ctx.chats.history(chat.id,limit=10)]
            # Sequential bounded reads avoid orphan tasks if any source fails.
            for read in (policy_history,rules_history,trust_history,restriction_history,blocklist_history):
                rows.extend((dict(row),'Canonical audit') for row in await asyncio.wait_for(read(ctx,chat.id),15))
            if not await authorized():
                raise LogInputError('Administrator permissions changed. Moderation log withheld.')
            rows=sorted(rows,key=lambda item:timestamp(item[0]),reverse=True)[:10]
            pages=max(1,(len(rows)+2)//3)
            if page>pages:
                raise LogInputError(f'Choose a moderation log page from 1 to {pages}.')
            selected=rows[(page-1)*3:page*3]
            table=Table(headers=('Action','Moderator','Target','When UTC'),rows=tuple((
                clip(row.get('action','?'),64).upper(),clip(row.get('actor'),20),clip(row.get('target'),20),
                time.strftime('%d %b %H:%M',time.gmtime(timestamp(row)))) for row,_ in selected))
            lines=[f"{i}. {source} · {clip(row.get('reason') or 'no reason',160)}" for i,(row,source) in enumerate(selected,start=(page-1)*3+1)]
            await reply(message,panel('Moderation log',icon=ctx.theme.emoji('stats'),table=table if selected else None,
                lines=lines if selected else ['No recent entries in the available audit sources.'],
                footer=f'Page {page}/{pages} · /modlog [page] · newest first · UTC',
                note='Recent window: up to 10 merged entries, not a complete audit export. Local audit and canonical audit may overlap; entries are not deduplicated. Recorded outcomes (including pending/failed) are not proof of current Telegram state. Group-visible reason previews; do not store secrets in moderation reasons. Pages are live, not a frozen snapshot.'))
        except LogInputError as error:
            await reply(message,panel('Moderation log request',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except Exception as error:
            logger.warning('#Errors Moderation log unavailable (%s)',type(error).__name__)
            await reply(message,panel('Moderation log request',icon=ctx.theme.emoji('warn'),lines=[
                'Moderation history or permissions unavailable. No partial log displayed; no automatic retry.']))
    return modlog
