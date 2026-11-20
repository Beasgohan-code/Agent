"""Rich warning removals; one awaited store, no implied Telegram restriction undo."""
import asyncio
import logging
from pyrogram.enums import ChatType
from ...platform.warnings import WarningStoreError
from ...ui.tables import panel,kv_table
from ...utils.rich import reply
from .restrictions import target_and_reason

COMMANDS=('rmwarn','resetwarn','resetallwarns')
logger=logging.getLogger(__name__)


class RemovalInputError(ValueError):
    """Locally authored safe validation."""


def build(ctx,*,include_group_alias=False):
    from . import is_moderator,target_is_protected

    def handler(command):
        async def call(client,message):
            user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
            committed=False
            try:
                if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise RemovalInputError('Use your personal administrator identity inside a group.')
                if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                    raise RemovalInputError('You need current Restrict members permission to clear warnings.')
                if command=='resetallwarns':
                    if (getattr(message,'text','') or '').split()[1:]!=['confirm']:
                        await reply(message,panel('Confirm group warning reset',icon=ctx.theme.emoji('warn'),
                            table=kv_table([('Scope',str(chat.id)),('Action','Clear every active warning in this group'),('History','Retained')]),
                            note='Run /resetallwarns confirm explicitly to proceed. This does not unban or unmute anyone.'))
                        return
                    if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                        raise RemovalInputError('Administrator permissions changed. No warnings cleared.')
                    from ...platform.warnings import reset_group
                    cleared=await reset_group(ctx.chats,chat.id,actor=user.id,request_id=message.id)
                    committed=True
                    await reply(message,panel('Group warning reset',icon=ctx.theme.emoji('check'),
                        table=kv_table([('Group',str(chat.id)),('Moderator',str(user.id)),('Warnings cleared',str(cleared)),('Status','Committed')]),
                        lines=[f'Group reset committed: {cleared} active warnings cleared.'],
                        note='History retained; Telegram restrictions unchanged. No unban or unmute was requested.'))
                    return
                source=getattr(message,'reply_to_message',None)
                if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                    raise RemovalInputError('Reply to a message from this group.')
                try:
                    target,extra=await asyncio.wait_for(target_and_reason(client,message),5)
                except ValueError:
                    raise RemovalInputError(f'Usage: /{command} @username or positive ID, or reply without arguments.') from None
                if type(target) is not int or not 0<target<2**63 or extra:
                    raise RemovalInputError(f'Usage: /{command} @username or positive ID, or reply without arguments.')
                if await asyncio.wait_for(target_is_protected(client,chat.id,target),5):
                    raise RemovalInputError('Cannot act on an administrator or unverified target.')
                if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                    raise RemovalInputError('Administrator permissions changed. No warnings cleared.')
                single=command in ('unwarn','rmwarn')
                cleared=(await ctx.chats.aclear_warning(chat.id,target) if single else await ctx.chats.aclear_all_warnings(chat.id,target))
                committed=True
                audit=''
                try:
                    ctx.chats.log(chat.id,command,actor_id=user.id,target_id=target,reason=f'{int(cleared)} cleared')
                except Exception:
                    logger.warning('#Errors Warning removal local audit unconfirmed')
                    audit=' Local audit unconfirmed.'
                await reply(message,panel('Warning cleared' if cleared and single else 'Warnings cleared' if cleared else 'No warning removed',icon=ctx.theme.emoji('check' if cleared else 'info'),
                    table=kv_table([('Member',str(target)),('Moderator',str(user.id)),('Warnings cleared',str(int(cleared))),('Operation','Latest active warning' if single else 'All active warnings for this member'),('Status','Committed')]),
                    lines=[] if cleared else ['That member has no active warnings.'],
                    note='History retained. No Telegram ban or mute was changed.'+audit))
            except (RemovalInputError,WarningStoreError) as error:
                await reply(message,panel('Warning removal status',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
            except Exception as error:
                logger.warning('#Errors Warning removal unavailable (%s)',type(error).__name__)
                await reply(message,panel('Warning removal status',icon=ctx.theme.emoji('warn'),lines=[
                    'Warning clear committed; result delivery unconfirmed. Check /warns before further action.' if committed else
                    'Warning removal unconfirmed. Check /warns before retrying; no automatic retry.']))
        return call
    commands=('unwarn',*COMMANDS,*(('resetwarns',) if include_group_alias else ()))
    return {command:handler(command) for command in commands}
