"""Strict anti-spam command UI; policy storage and enforcement stay canonical."""
import asyncio
import logging
from pyrogram.enums import ChatType
from ...platform.antispam import read_policy,change_policy,PolicyError
from ...ui.tables import panel,kv_table
from ...utils.rich import reply

logger=logging.getLogger(__name__)
USAGE='Usage: /antispam on|off|limit 7|action mute|links off|invites off|flood on|duplicates on|mute 300|keyword phrase|keyword-clear'


class AntispamInputError(ValueError):
    """Safe locally authored input validation."""


def parse(text):
    args=(text or '').split(maxsplit=2)[1:]
    if not args:
        return None,None
    op=args[0].lower()
    value=args[1].strip().lower() if len(args)>1 else None
    if op in ('on','off','keyword-clear'):
        valid=value is None
    elif op in ('links','invites','flood','duplicates'):
        valid=value in ('on','off')
    elif op=='action':
        valid=value in ('delete','warn','mute','kick','ban')
    elif op in ('limit','mute'):
        low,high=(2,1000) if op=='limit' else (30,366*86400)
        valid=isinstance(value,str) and value.isascii() and value.isdecimal() and len(value)<=9 and low<=int(value)<=high
    elif op in ('keyword','keywords'):
        valid=isinstance(value,str) and 1<=len(value)<=200
    else:
        valid=False
    if not valid:
        raise AntispamInputError(USAGE+' · limit: 2–1000; mute: 30–31622400 seconds; phrase: 1–200 characters. Values outside bounds are rejected, not clamped.')
    return op,value


def build(ctx):
    from . import is_moderator

    async def antispam(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        committed=False
        async def authorized():
            return await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5)
        try:
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise AntispamInputError('Use your personal administrator identity inside a group.')
            if not await authorized():
                raise AntispamInputError('Current Manage chat administrator permission required.')
            op,value=parse(getattr(message,'text',''))
            if op is not None:
                if not await authorized():
                    raise AntispamInputError('Administrator permissions changed. No policy change attempted.')
                policy=await change_policy(ctx,chat.id,op,value,actor=user.id)
                committed=True
            else:
                policy=await read_policy(ctx,chat.id)
            if not await authorized():
                raise AntispamInputError('Administrator permissions changed. Policy change committed; details withheld.' if committed else 'Administrator permissions changed. Policy details withheld.')
            action=policy['action']
            if action=='mute':
                action+=f" ({policy['mute_seconds']}s)"
            await reply(message,panel('Anti-spam settings',icon=ctx.theme.emoji('shield'),table=kv_table([
                ('Moderator',str(user.id)),('Status','Committed' if committed else 'Current saved policy'),
                ('Flood',f"{policy['flood_messages']} per {policy['flood_window_seconds']}s ({'on' if policy['flood_enabled'] else 'off'})"),
                ('Duplicates',f"threshold {policy['duplicate_threshold']} ({'on' if policy['duplicate_enabled'] else 'off'})"),
                ('Links','blocked' if policy['links_enabled'] else 'allowed'),
                ('Invites','blocked' if policy['invites_enabled'] else 'allowed'),
                ('Keywords',f"{len(policy.get('blocked_keywords') or [])} configured ({'on' if policy['keywords_enabled'] else 'off'}); phrases withheld"),
                ('Action',action),
                ('Additional flood modes',f"consecutive {policy.get('consecutive_limit',0)}; timed {policy.get('timed_flood_count',0)} per {policy.get('timed_flood_seconds',0)}s (0 = off)")]),
                note=USAGE+' · /flood for additional flood-mode details. Saved settings are not a live enforcement check; actions depend on the running watcher and bot permissions. Staff and approved members are exempt from automatic anti-spam, not manual moderation. /antispam off also disables additional flood modes. Group-visible reply.'))
        except (AntispamInputError,PolicyError) as error:
            await reply(message,panel('Anti-spam request',icon=ctx.theme.emoji('warn'),lines=[str(error)]))
        except Exception as error:
            logger.warning('#Errors Anti-spam request unavailable (%s)',type(error).__name__)
            await reply(message,panel('Anti-spam request',icon=ctx.theme.emoji('warn'),lines=[
                'Policy change committed; result delivery or permissions unconfirmed. Inspect /antispam before further action.' if committed else
                'Policy state or permissions unavailable. Change unconfirmed; inspect /antispam before retrying. No automatic retry.']))
    return antispam
