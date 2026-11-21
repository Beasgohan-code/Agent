"""Manual mute target/duration parity with live authority and explicit acknowledgement."""
import asyncio
import logging
import re
from datetime import datetime,timedelta,timezone
from pyrogram.enums import ChatType,ChatMemberStatus
from .restrictions import target_and_reason
from ...utils.rich import reply
from ...ui.tables import panel,kv_table
from .mute_controls import setup,issue,bind

logger=logging.getLogger(__name__)


class MuteInputError(ValueError):
    """Safe command validation."""


def duration_and_reason(body):
    args=body.split(maxsplit=1)
    if not args:
        return 600,''
    token=args[0].lower()
    match=re.fullmatch(r'([0-9]{1,8})([smhd]?)',token)
    if match:
        seconds=int(match[1])*{'':60,'s':1,'m':60,'h':3600,'d':86400}[match[2]]
        if not 60<=seconds<=366*86400:
            raise MuteInputError('Mute duration must be 60s–366d. Bare numbers are minutes.')
        return seconds,args[1] if len(args)>1 else ''
    if token[:1].isdigit() or token.startswith(('-','+')):
        raise MuteInputError('Invalid mute duration. Use 1m, 2h, 1d or minutes (60s–366d).')
    return 600,body


def build(ctx):
    from . import is_moderator,target_is_protected,MUTE_PERMISSIONS,duration_label
    setup(ctx)

    async def mute(client,message):
        user,chat=getattr(message,'from_user',None),getattr(message,'chat',None)
        if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
            await reply(message,'Use your personal administrator identity in a group.')
            return
        attempted=False
        confirmed=False
        try:
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise MuteInputError('Current Restrict members administrator permission is required.')
            source=getattr(message,'reply_to_message',None)
            if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                raise MuteInputError('Reply to a member from this group.')
            try:
                uid,body=await asyncio.wait_for(target_and_reason(client,message),5)
            except ValueError:
                raise MuteInputError('Reply or use /mute @username|positive_ID [duration] [reason].') from None
            if type(uid) is not int or not 0<uid<2**63:
                raise MuteInputError('A positive personal target identity is required.')
            seconds,reason=duration_and_reason(body)
            me=await asyncio.wait_for(client.get_me(),5)
            if uid in (user.id,me.id):
                raise MuteInputError('Cannot mute yourself or this bot.')
            if await asyncio.wait_for(target_is_protected(client,chat.id,uid),5):
                raise MuteInputError('Cannot act on an administrator or unverified target. Action not attempted.')
            bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
            if bot.status!=ChatMemberStatus.OWNER and not (bot.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(bot,'privileges',None),'can_restrict_members',False)):
                raise MuteInputError('This bot needs Restrict members permission.')
            if not await asyncio.wait_for(is_moderator(client,message,need='can_restrict_members'),5):
                raise MuteInputError('Your Restrict members permission changed. No mute requested.')
            attempted=True
            until=datetime.now(timezone.utc)+timedelta(seconds=seconds)
            result=await asyncio.wait_for(client.restrict_chat_member(chat.id,uid,MUTE_PERMISSIONS,until_date=until),10)
            if result is not True:
                raise RuntimeError('Mute acknowledgement unavailable')
            confirmed=True
            try:
                ctx.chats.log(chat.id,'mute',actor_id=user.id,target_id=uid,reason=reason[:500])
                audit=''
            except Exception:
                logger.warning('#Errors Mute local audit unconfirmed')
                audit=' Local audit unconfirmed.'
            token,keyboard=issue(ctx,chat.id,uid,until)
            card=panel('Member muted',icon=ctx.theme.emoji('lock'),
                table=kv_table([('Member',str(uid)),('Moderator',str(user.id)),('Duration',duration_label(seconds)),('Reason',reason[:500] or 'No reason supplied'),('Status','Telegram confirmed')]),
                note='Unmute restores current group permissions. Button expires in 15 minutes or after a bot restart; current admin rights required. You can also use /unmute '+str(uid)+'.'+audit)
            sent=None
            try:
                sent=await reply(message,card,reply_markup=keyboard)
            finally:
                # Discard unbound controls on failed delivery or cancellation.
                bind(ctx,token,sent)
        except MuteInputError as error:
            await reply(message,panel('Mute not applied',icon=ctx.theme.emoji('warn'),lines=[str(error)],note='Use /mute @username or ID [duration] [reason], or reply with /mute 2m reason.'))
        except Exception as error:
            logger.warning('#Errors Mute unavailable (%s)',type(error).__name__)
            if confirmed:
                # Delivery or local presentation failure cannot undo the action.
                return
            await reply(message,panel('Mute status',icon=ctx.theme.emoji('warn'),lines=[f'Mute unconfirmed ({type(error).__name__}). Inspect Telegram before retrying; no automatic retry.' if attempted else 'Target or permissions unavailable. Action not attempted.']))
    return mute
