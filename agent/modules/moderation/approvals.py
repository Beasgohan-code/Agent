"""Explicit approval commands backed by the existing canonical trust store."""
import asyncio
import logging
from pyrogram.enums import ChatType
from ...platform.group_trust import trusted_members,TrustError
from ...ui.tables import Table,panel,kv_table
from ...utils.rich import reply
from .restrictions import target_and_reason

logger=logging.getLogger(__name__)
COMMANDS=('approve','unapprove','approval','approved')
NOTE='Approval exempts a member from automatic anti-spam actions, not manual moderation. It does not grant Telegram administrator rights.'


class ApprovalInputError(ValueError):
    """Safe locally authored validation message."""


def build(ctx):
    from . import is_moderator

    def handler(command):
        async def call(client,message):
            user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
            committed=False
            async def authorized():
                return await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5)
            try:
                if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise ApprovalInputError('Use approval commands as yourself inside a group.')
                if not await authorized():
                    raise ApprovalInputError('Current Manage chat administrator permission required.')
                if command=='approved':
                    args=(getattr(message,'text','') or '').split()[1:]
                    if (len(args)>1 or args and (not args[0].isascii() or not args[0].isdecimal() or len(args[0])>8 or int(args[0])<1)):
                        raise ApprovalInputError('Usage: /approved [positive page number]')
                    page=int(args[0]) if args else 1
                    members=sorted(await trusted_members(ctx,chat.id))
                    if not await authorized():
                        raise ApprovalInputError('Administrator permissions changed. Approval list withheld.')
                    pages=max(1,(len(members)+19)//20)
                    if page>pages:
                        raise ApprovalInputError(f'Choose an approvals page from 1 to {pages}.')
                    await reply(message,panel('Approved members',table=Table(headers=('Member ID',),rows=tuple((str(uid),) for uid in members[(page-1)*20:page*20])),
                        lines=[] if members else ['No approved members in this group.'],footer=f'Page {page}/{pages} · /approved [page]',note=NOTE+' Group-visible reply; pages reflect current state.'))
                    return
                source=getattr(message,'reply_to_message',None)
                if source is not None and (getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id or getattr(source,'from_user',None) is None):
                    raise ApprovalInputError('Reply to a personal member from this group.')
                try:
                    uid,remainder=await asyncio.wait_for(target_and_reason(client,message),5)
                except ValueError:
                    raise ApprovalInputError('Reply to a member or provide one positive ID, @username or text mention.') from None
                if type(uid) is not int or not 0<uid<2**63 or remainder.strip():
                    raise ApprovalInputError('Provide exactly one personal target; no extra arguments.')
                if not await authorized():
                    raise ApprovalInputError('Administrator permissions changed. No approval change attempted.')
                desired={'approve':True,'unapprove':False}.get(command)
                members=await trusted_members(ctx,chat.id,toggle=uid if desired is not None else None,actor=user.id,approved=desired)
                committed=desired is not None
                if not await authorized():
                    raise ApprovalInputError('Administrator permissions changed. Approval change committed; details withheld.' if committed else 'Administrator permissions changed. Approval status withheld.')
                state=uid in members
                title=('Approved member' if state else 'Approval removed') if committed else 'Approval status'
                await reply(message,panel(title,icon=ctx.theme.emoji('check'),table=kv_table([
                    ('Member',str(uid)),('Moderator',str(user.id)),('Approval','Approved' if state else 'Not approved'),
                    ('Status','Committed (idempotent desired state)' if committed else 'Current state')]),note=NOTE))
            except (ApprovalInputError,TrustError) as error:
                await reply(message,panel('Approval request',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
            except Exception as error:
                logger.warning('#Errors Approval request unavailable (%s)',type(error).__name__)
                await reply(message,panel('Approval request',icon=ctx.theme.emoji('warn'),lines=[
                    'Approval change committed; result delivery or permissions unconfirmed. Inspect /approval before further action.' if committed else
                    'Approval state or permissions unavailable. Change unconfirmed; inspect /approval before retrying. No automatic retry.']))
        return call
    return {command:handler(command) for command in COMMANDS}
