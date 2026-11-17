"""Admin warning-policy commands share one awaited source of truth."""
import asyncio
import re
import logging
from pyrogram.enums import ChatType
from ...platform.warning_policy import operate,PolicyError
from ...utils.rich import reply
from ...ui.tables import panel,kv_table

COMMANDS=('warnmode',)


def build(ctx):
    from ..moderation import is_moderator

    def handler(command):
        async def call(client,message):
            user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or user.id<=0 or getattr(user,'is_bot',False)
                    or getattr(message,'sender_chat',None) is not None):
                await reply(message,'Use your personal administrator identity in a group.')
                return
            try:
                if not await asyncio.wait_for(is_moderator(client,message,need='can_change_info'),5):
                    await reply(message,'Current Change chat info administrator permission is required.')
                    return
                args=(getattr(message,'text','') or '').split()[1:]
                changes=None
                if args:
                    changes={}
                    if command=='warnlimit':
                        if len(args)>2 or (args[0].lower() not in ('off','0') and (not re.fullmatch(r'[0-9]{1,2}',args[0]) or not 1<=int(args[0])<=20)):
                            raise PolicyError('Usage: /warnlimit 1–20 [mute|kick|ban], or /warnlimit off.')
                        changes['limit']=0 if args[0].lower()=='off' else int(args[0])
                        if len(args)==2:
                            if args[1].lower() not in ('mute','kick','ban'):
                                raise PolicyError('Unknown action. Use mute, kick or ban. No settings changed.')
                            changes['action']=args[1].lower()
                    elif command=='warnmode':
                        if len(args)!=1 or args[0].lower() not in ('mute','kick','ban'):
                            raise PolicyError('Usage: /warnmode mute|kick|ban. Use /warnlimit off to disable escalation.')
                        changes['action']=args[0].lower()
                    if not await asyncio.wait_for(is_moderator(client,message,need='can_change_info'),5):
                        raise PolicyError('Administrator permissions changed. No settings changed.')
                policy=await operate(ctx.chats,chat.id,actor=user.id,changes=changes)
                await reply(message,panel('Warning escalation policy',icon=ctx.theme.emoji('warn'),
                    table=kv_table([('Threshold',str(policy['limit'])),('Mode',policy['action'])]),
                    lines=['Warnings do not escalate in this group.' if not policy['limit'] else f"Threshold: {policy['limit']} active warnings."],
                    note='Saved policy for future warning escalation only; existing warnings/restrictions unchanged. Kick removes a member; ban is permanent. /warnlimit off disables escalation.'))
            except PolicyError as error:
                await reply(message,str(error))
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Warning settings unavailable (%s)',type(error).__name__)
                await reply(message,'Warning policy or permissions unavailable. Re-read before retrying; no automatic retry.')
        return call
    return {name:handler(name) for name in ('warnlimit',*COMMANDS)}
