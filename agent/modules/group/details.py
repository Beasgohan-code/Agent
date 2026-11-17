"""Live read-only rights/counts and guarded current-group metadata changes."""
import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from ...ui.screens import format_uptime
from pyrogram.enums import ChatType, ChatMemberStatus, ChatMembersFilter
from pyrogram.file_id import FileId, FileType
from ...ui.keyboards import nav_keyboard
from ...ui.tables import panel, kv_table, Table, markup
from ...utils.rich import reply
from ..moderation import is_moderator
from .admin import resolve, RIGHTS

COMMANDS = ('userstats','recentactivity','admincount','rights','setchatname','setchatdescription','setchatphoto')
logger = logging.getLogger(__name__)


class DetailInputError(ValueError):
    """Safe local validation, never API exception text."""


def build(ctx):
    def handler(command):
        async def call(client, message):
            user, chat = getattr(message,'from_user',None), getattr(message,'chat',None)
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or user.id<=0
                    or getattr(message,'sender_chat',None) is not None):
                await reply(message,'Use your personal administrator identity inside a group.')
                return
            modifying = command.startswith('setchat')
            need = 'can_change_info' if modifying else 'can_manage_chat'
            attempted = False
            try:
                if not await is_moderator(client,message,need=need):
                    raise DetailInputError('You do not have the current administrator permission required for this command.')
                parts=(getattr(message,'text','') or '').split(maxsplit=1)
                value=parts[1].strip() if len(parts)==2 else ''
                if command in ('userstats','recentactivity'):
                    if value:
                        raise DetailInputError(f'Usage: /{command} without arguments, in the current group.')
                    if command=='userstats':
                        count=await asyncio.wait_for(client.get_chat_members_count(chat.id),5)
                        if type(count) is not int or count<1:
                            raise RuntimeError('Member count not acknowledged')
                        monitor=getattr(ctx,'monitor',None)
                        registry=getattr(ctx,'registry',None)
                        rows=[('Members (live)',str(count)),
                              ('Bot uptime',format_uptime(monitor.snapshot().uptime_seconds) if monitor is not None else 'Unavailable'),
                              ('Registered commands',str(len(registry.active_commands())) if registry is not None else 'Unavailable')]
                        await reply(message,panel('Group and bot statistics',icon=ctx.theme.emoji('stats'),table=kv_table(rows),
                            note='Member count read live from Telegram for this group. Uptime/commands describe this bot process, not group presence, message activity, or all Telegram users.'),reply_markup=nav_keyboard(theme=ctx.theme))
                    else:
                        store=getattr(ctx,'chats',None)
                        if store is None:
                            raise RuntimeError('Group history unavailable')
                        events=store.history(chat.id,limit=10)
                        rows=tuple((datetime.fromtimestamp(float(event['at']),tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),str(event.get('action','unknown'))[:64]) for event in events)
                        await reply(message,panel('Recent recorded group actions',icon=ctx.theme.emoji('clock'),
                            table=Table(headers=('UTC','Action'),rows=rows) if rows else None,
                            lines=[] if rows else ['No actions recorded in this bot’s cached group history.'],
                            note='Latest 10 entries from this group’s cached moderation log, not a complete Telegram activity feed or authoritative full SQL audit. Reasons, message text and other-group records are not shown.'),reply_markup=nav_keyboard(theme=ctx.theme))
                    return
                if command=='admincount':
                    if value:
                        raise DetailInputError('Usage: /admincount')
                    async def count():
                        total=0
                        async for member in client.get_chat_members(chat.id,filter=ChatMembersFilter.ADMINISTRATORS):
                            total+=1
                            if total>1000:
                                raise DetailInputError('Administrator count exceeds the supported 1,000-entry bound.')
                        return total
                    total=await asyncio.wait_for(count(),10)
                    await reply(message,panel('Administrator count',icon=ctx.theme.emoji('crown'),
                        table=kv_table([('Administrators',str(total))]),note='Live Telegram administrator-list count, including bots and anonymous admins. No hidden admin identities are exposed.'),reply_markup=nav_keyboard(theme=ctx.theme))
                    return
                if command=='rights':
                    if not value and getattr(message,'reply_to_message',None) is None:
                        raise DetailInputError('Reply to a member or use /rights @username or positive ID.')
                    # Existing resolver is shared; any raw upstream errors remain redacted.
                    try:
                        target=await asyncio.wait_for(resolve(client,message),5)
                    except ValueError:
                        raise DetailInputError('Unable to resolve target. Use one username/ID or reply.') from None
                    target_id=getattr(target,'id',None)
                    if type(target_id) is not int or target_id<=0:
                        raise DetailInputError('A personal target identity is required.')
                    member=await asyncio.wait_for(client.get_chat_member(chat.id,target_id),5)
                    privileges=getattr(member,'privileges',None)
                    owner=member.status==ChatMemberStatus.OWNER
                    admin=member.status==ChatMemberStatus.ADMINISTRATOR
                    rows=tuple((name,markup(ctx.theme.emoji('check' if (bool(getattr(privileges,name,False)) if name=='is_anonymous' else owner or (admin and getattr(privileges,name,False))) else 'cross'))) for name in (*RIGHTS,'can_promote_members','is_anonymous'))
                    await reply(message,panel('Current administrator rights',icon=ctx.theme.emoji('shield'),
                        table=Table(headers=('Permission','Granted'),rows=rows),
                        lines=[f'Member: <code>{target_id}</code>'],
                        note='Read-only Telegram snapshot, not a rights editor. Owner privileges are implicit; anonymous status is reported as a setting, not a grant.'),reply_markup=nav_keyboard(theme=ctx.theme))
                    return
                if command=='setchatname':
                    if not 1<=len(value)<=128:
                        raise DetailInputError('Usage: /setchatname text — 1–128 characters.')
                elif command=='setchatdescription':
                    if not 1<=len(value)<=255:
                        raise DetailInputError('Usage: /setchatdescription text — 1–255 characters, or /setchatdescription clear.')
                    value='' if value.lower()=='clear' else value
                else:
                    if value:
                        raise DetailInputError('Reply to a photo with /setchatphoto, without arguments.')
                    source=getattr(message,'reply_to_message',None)
                    if source is None or getattr(getattr(source,'chat',None),'id',None)!=chat.id or getattr(source,'has_protected_content',False):
                        raise DetailInputError('Reply to an unprotected photo from this group.')
                    value=getattr(getattr(source,'photo',None),'file_id',None)
                    try:
                        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,2048}',value) or os.path.isfile(value):
                            raise ValueError()
                        decoded=FileId.decode(value)
                        if decoded.file_type!=FileType.PHOTO or decoded.url:
                            raise ValueError()
                    except Exception:
                        raise DetailInputError('A valid Telegram photo reference is required; paths, URLs and documents are not accepted.') from None
                me=await asyncio.wait_for(client.get_me(),5)
                member=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
                if member.status!=ChatMemberStatus.OWNER and not (member.status==ChatMemberStatus.ADMINISTRATOR and getattr(getattr(member,'privileges',None),'can_change_info',False)):
                    raise DetailInputError('This bot needs Change chat info permission.')
                if not await is_moderator(client,message,need='can_change_info'):
                    raise DetailInputError('Your administrator permissions changed. No change requested.')
                attempted=True
                if command=='setchatname':
                    result=await asyncio.wait_for(client.set_chat_title(chat.id,value),10)
                elif command=='setchatdescription':
                    result=await asyncio.wait_for(client.set_chat_description(chat.id,value),10)
                else:
                    result=await asyncio.wait_for(client.set_chat_photo(chat.id,photo=value),10)
                if result is not True:
                    raise RuntimeError('Telegram acknowledgement unavailable')
                try:
                    ctx.chats.log(chat.id,command,actor_id=user.id,reason='Telegram-confirmed chat metadata update')
                    audit=''
                except Exception:
                    logger.warning('#Errors Chat metadata audit unconfirmed')
                    audit=' Local audit recording unconfirmed.'
                await reply(message,'Chat update confirmed by Telegram.'+audit)
            except DetailInputError as error:
                await reply(message,str(error))
            except Exception as error:
                logger.warning('#Errors Chat detail action unavailable (%s)',type(error).__name__)
                await reply(message,'Chat update unconfirmed. Inspect current chat info before retrying; no automatic retry.' if attempted else 'Chat information or permissions unavailable. No chat change requested.')
        return call
    return {name:handler(name) for name in COMMANDS}
