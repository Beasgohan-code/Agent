"""Administrator commands; mutations always authorize against live Telegram state."""

import html
import asyncio
import logging
import re
import unicodedata
from pyrogram.enums import ChatMemberStatus, ChatType, ChatMembersFilter
from pyrogram.types import ChatPrivileges
from ...platform.admin_settings import options, denied, AdminStateError
from ...ui.tables import panel, Table
from ...utils.rich import reply
from ..moderation import is_moderator

COMMANDS = ("allsettings", "tagstats", "tpromote", "promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror")
# Delegation never includes adding administrators or anonymous identity.
RIGHTS = (
    "can_manage_chat",
    "can_delete_messages",
    "can_manage_video_chats",
    "can_restrict_members",
    "can_change_info",
    "can_invite_users",
    "can_pin_messages",
)


async def resolve(client, message):
    replied = getattr(getattr(message, "reply_to_message", None), "from_user", None)
    args = (getattr(message, "text", "") or "").split()
    if len(args) > 2:
        raise ValueError("Reply to a user or provide one username, mention or user ID.")
    if replied is not None:
        return replied
    for entity in getattr(message, "entities", None) or []:
        user = getattr(entity, "user", None)
        if user is not None:
            return user
    if len(args) != 2:
        raise ValueError("Reply to a user or provide a username, mention or user ID.")
    value = args[1]
    if value.isascii() and value.isdecimal() and len(value) < 20:
        value = int(value)
    elif not value.startswith("@"):
        raise ValueError("Use a positive user ID or @username.")
    return await client.get_users(value)


async def promotion_target(client,message):
    """Parse title only for promotion; other consumers keep strict target syntax."""
    parts=(getattr(message,'text','') or '').split(maxsplit=1)
    tail=parts[1] if len(parts)==2 else ''
    source=getattr(message,'reply_to_message',None)
    if source is not None:
        if getattr(getattr(source,'chat',None),'id',None)!=message.chat.id:
            raise ValueError('Reply to a member from this group.')
        target=getattr(source,'from_user',None)
        if target is None:
            raise ValueError('Reply to a personal member identity.')
        title=tail
        value=None
    else:
        args=tail.split(maxsplit=1)
        if not args:
            mentions=[getattr(entity,'user',None) for entity in getattr(message,'entities',None) or [] if getattr(entity,'user',None) is not None]
            if mentions:
                return mentions[0],''
            raise ValueError('Usage: /promote @username|positive_ID [title], or reply /promote [title].')
        value=args[0]
        title=args[1] if len(args)==2 else ''
        if value.isascii() and value.isdecimal() and len(value)<=19 and 0<int(value)<2**63:
            value=int(value)
        elif not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',value):
            # Preserve Telegram text-mention targeting without accepting arbitrary strings.
            mentions=[getattr(entity,'user',None) for entity in getattr(message,'entities',None) or [] if getattr(entity,'user',None) is not None]
            if mentions and not title:
                return mentions[0],''
            raise ValueError('Use a positive user ID or @username, or reply to a member.')
        target=None
    if len(title)>16 or any(unicodedata.category(char).startswith('C') for char in title):
        raise ValueError('Administrator title must be 1–16 characters with no control/format characters. Omit it for no custom title. Telegram may reject emoji titles.')
    if target is None:
        target=await asyncio.wait_for(client.get_users(value),5)
    return target,title


def build(ctx):
    snapshots = {}

    async def refresh(client, chat_id):
        members = [
            member
            async for member in client.get_chat_members(
                chat_id, filter=ChatMembersFilter.ADMINISTRATORS
            )
        ]
        snapshots[chat_id] = members
        return members

    async def run(client, message, command):
        chat = getattr(message, "chat", None)
        if getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await reply(message, "Use administrator commands inside a group.")
            return
        try:
            if command == "adminlist":
                members = await refresh(client, chat.id)
                rows = []
                for member in members:
                    user = getattr(member, "user", None)
                    if user is not None and not getattr(getattr(member, "privileges", None), "is_anonymous", False):
                        rows.append(
                            (
                                str(user.id),
                                getattr(user, "first_name", "") or "Member",
                                "Owner"
                                if member.status == ChatMemberStatus.OWNER
                                else "Admin",
                            )
                        )
                args = (message.text or "").split()
                if len(args) > 2 or (
                    len(args) == 2
                    and (
                        not args[1].isascii()
                        or not args[1].isdecimal()
                        or len(args[1]) > 8
                        or int(args[1]) < 1
                    )
                ):
                    raise ValueError("Usage: /adminlist [page]")
                page = int(args[1]) if len(args) == 2 else 1
                pages = max(1, (len(rows) + 19) // 20)
                if page > pages:
                    raise ValueError(f"Choose an admin list page from 1 to {pages}.")
                await reply(
                    message,
                    panel(
                        "Group administrators",
                        table=Table(
                            headers=("ID", "Name", "Role"),
                            rows=tuple(rows[(page - 1) * 20 : page * 20]),
                        ),
                        footer=f"Page {page}/{pages} · /adminlist [page]",
                    ),
                )
                return
            user = getattr(message, "from_user", None)
            # Settings and privilege changes require accountable personal identity.
            if (
                type(getattr(user, "id", None)) is not int
                or user.id <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                raise ValueError(
                    "Use your personal identity for administrator changes."
                )
            need = (
                "can_promote_members"
                if command in ("promote", "demote")
                else "can_manage_chat"
            )
            if not await is_moderator(client, message, need=need):
                await denied(
                    ctx, message, "You do not have the required group-admin permission."
                )
                return
            if command in ("anonadmin", "adminerror"):
                args = (message.text or "").split()
                if len(args) == 1:
                    state = await options(ctx, chat.id)
                elif len(args) == 2 and args[1].lower() in ("yes", "no", "on", "off"):
                    state = await options(
                        ctx,
                        chat.id,
                        setting=command,
                        enabled=args[1].lower() in ("yes", "on"),
                        actor=user.id,
                    )
                else:
                    raise ValueError(f"Usage: /{command} yes|no|on|off")
                warning = (
                    "\nWarning: anonymous group senders can bypass granular group permission checks. Personal-identity and Owner-only safeguards still apply."
                    if command == "anonadmin"
                    else ""
                )
                await reply(
                    message, f"{command}: {'on' if state[command] else 'off'}{warning}"
                )
                return
            if command == "admincache":
                if len((message.text or "").split()) != 1:
                    raise ValueError("Usage: /admincache")
                members = await refresh(client, chat.id)
                await reply(
                    message,
                    f"Administrator snapshot refreshed: {len(members)} admins. Permission checks always use current Telegram rights, not this snapshot.",
                )
                return
            title = ""
            if command == "promote":
                target, title = await promotion_target(client, message)
            else:
                target = await resolve(client, message)
            target_id = getattr(target, "id", None)
            if type(target_id) is not int or not 0 < target_id < 2**63:
                raise ValueError("Invalid user identity.")
            me = await asyncio.wait_for(client.get_me(),5)
            if target_id in (user.id, me.id):
                raise ValueError(
                    "You cannot change your own or my administrator privileges here."
                )
            bot = await asyncio.wait_for(client.get_chat_member(chat.id, me.id),5)
            caller = await asyncio.wait_for(client.get_chat_member(chat.id, user.id),5)
            member = await asyncio.wait_for(client.get_chat_member(chat.id, target_id),5)
            if bot.status != ChatMemberStatus.ADMINISTRATOR or not getattr(
                getattr(bot, "privileges", None), "can_promote_members", False
            ):
                raise ValueError("I need the Add administrators permission.")
            if caller.status != ChatMemberStatus.OWNER and (
                caller.status != ChatMemberStatus.ADMINISTRATOR
                or not getattr(
                    getattr(caller, "privileges", None), "can_promote_members", False
                )
            ):
                raise ValueError(
                    "Your Add administrators permission is no longer available."
                )
            if member.status == ChatMemberStatus.OWNER:
                raise ValueError("The group owner cannot be changed here.")
            if command == "promote" and member.status == ChatMemberStatus.ADMINISTRATOR:
                raise ValueError(
                    "This user is already an administrator; no privileges changed."
                )
            if command == "promote" and member.status != ChatMemberStatus.MEMBER:
                raise ValueError(
                    "The user must be an unrestricted member of this group first."
                )
            if command == "demote" and member.status != ChatMemberStatus.ADMINISTRATOR:
                raise ValueError("This user is not an administrator.")
            if command == "demote" and not getattr(member, "can_be_edited", False):
                raise ValueError(
                    "Telegram does not allow me to edit this administrator."
                )
            granted = {
                right: command == "promote"
                and bool(getattr(bot.privileges, right, False))
                and (
                    caller.status == ChatMemberStatus.OWNER
                    or bool(getattr(caller.privileges, right, False))
                )
                for right in RIGHTS
            }
            privileges = ChatPrivileges(
                **granted, can_promote_members=False, is_anonymous=False
            )
            if not await asyncio.wait_for(is_moderator(client,message,need='can_promote_members'),5):
                raise ValueError('Your Add administrators permission changed. No administrator change requested.')
            result = await asyncio.wait_for(client.promote_chat_member(
                chat.id, target_id, privileges=privileges
            ),10)
            if result is not True:
                raise ValueError(
                    "Telegram did not confirm the administrator change. Check current rights before retrying."
                )
            snapshots.pop(chat.id, None)
            try:
                ctx.chats.log(chat.id, command, actor_id=user.id, target_id=target_id)
                audit=''
            except Exception:
                logging.getLogger(__name__).warning('#Errors Administrator change local audit unconfirmed')
                audit=' Local audit unconfirmed.'
            if command=='promote' and title:
                try:
                    # Promotion is already confirmed: title failure must never suggest rollback.
                    if not await asyncio.wait_for(is_moderator(client,message,need='can_promote_members'),5):
                        raise RuntimeError('Caller authority changed')
                    acknowledged=await asyncio.wait_for(client.set_administrator_title(chat.id,target_id,title),10)
                    if acknowledged is not True:
                        raise RuntimeError('Title acknowledgement unavailable')
                except Exception as error:
                    logging.getLogger(__name__).warning('#Errors Administrator title unconfirmed (%s)',type(error).__name__)
                    await reply(message,'Promotion confirmed by Telegram; title unconfirmed. Inspect the administrator list before retrying; no automatic retry or rollback.'+audit)
                    return
                await reply(message,f'Promotion and title confirmed by Telegram for <code>{target_id}</code>.'+audit)
                return
            await reply(
                message,
                f"User <code>{target_id}</code> {'promoted' if command == 'promote' else 'demoted'}."+audit,
            )
        except (ValueError, AdminStateError) as error:
            await reply(message, html.escape(str(error)))
        except Exception:
            await reply(
                message,
                "Telegram administrator operation could not be confirmed. Check current rights before retrying.",
            )

    def handler(command):
        async def call(client, message):
            await run(client, message, command)

        return call

    return {**{command: handler(command) for command in COMMANDS if command not in ("tpromote", "allsettings", "tagstats")}, "tpromote": build_tpromote(ctx), **build_tagging_settings(ctx)}


class TemporaryPromotionInputError(ValueError):
    """Safe locally authored command validation."""


def build_tpromote(ctx):
    """Owner-authorized limited temporary promotion with durable expiry admission."""
    from datetime import datetime,timedelta,timezone
    import inspect
    from ...platform.timed_promotions import reserve,finish,read,pool,PromotionError
    from ..moderation.restrictions import target_and_reason
    from ..moderation.antiflood import duration
    from ...ui.tables import kv_table

    async def tpromote(client,message):
        chat,user=getattr(message,'chat',None),getattr(message,'from_user',None)
        dispatched=False
        request=None
        try:
            if (getattr(chat,'type',None)!=ChatType.SUPERGROUP
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise TemporaryPromotionInputError('Use your personal account in a supergroup.')
            async def owner():
                current=await asyncio.wait_for(client.get_chat_member(chat.id,user.id),5)
                if current.status!=ChatMemberStatus.OWNER:
                    raise TemporaryPromotionInputError('Only the current group owner can use /tpromote.')
            await owner()
            db=getattr(ctx,'db',None)
            pool(db)
            args=(getattr(message,'text','') or '').split()[1:]
            if args==['status']:
                async with db._pool.acquire(timeout=5) as conn:
                    rows=await conn.fetch('''SELECT id,target_id,state,expires_at FROM agent_timed_promotions
                        WHERE tenant=$1 AND group_id=$2 ORDER BY created_at DESC,id DESC LIMIT 10''',db.scope,chat.id,timeout=5)
                await owner()
                await reply(message,panel('Temporary promotions',lines=[f"{r['target_id']} · {r['state']} · {r['expires_at'].strftime('%d %b %H:%M UTC')} · {r['id']}" for r in rows] or ['No temporary promotions.'],note='Review means automatic action stopped. Check Telegram, then demote manually if needed.'))
                return
            if len(args)==2 and args[0]=='resolve':
                identity=args[1]
                if not re.fullmatch('[0-9a-f]{32}',identity):
                    raise TemporaryPromotionInputError('Usage: /tpromote resolve request_ID')
                row=await read(db,identity,group=chat.id)
                if row is None or row['state']!='review':
                    raise TemporaryPromotionInputError('No review-needed request in this group.')
                member=await asyncio.wait_for(client.get_chat_member(chat.id,row['target_id']),5)
                if member.status not in (ChatMemberStatus.MEMBER,ChatMemberStatus.RESTRICTED,ChatMemberStatus.LEFT,ChatMemberStatus.BANNED):
                    raise TemporaryPromotionInputError('Demote this member manually in Telegram before resolving.')
                await owner()
                await finish(db,identity,'closed',expected='review')
                await reply(message,'Review closed. No Telegram permissions changed.')
                return
            if not getattr(ctx,'timed_promotions_running',False):
                raise TemporaryPromotionInputError('Temporary promotion recovery is not running. No promotion attempted.')
            source=getattr(message,'reply_to_message',None)
            if source is not None and getattr(getattr(source,'chat',None),'id',chat.id)!=chat.id:
                raise TemporaryPromotionInputError('Reply to a member of this group.')
            uid,rest=await asyncio.wait_for(target_and_reason(client,message),5)
            if len(rest.split())!=1:
                raise TemporaryPromotionInputError('Use /tpromote @user 5m or reply /tpromote 5m. Status: /tpromote status')
            try:
                seconds=duration(rest.strip())
            except ValueError:
                raise TemporaryPromotionInputError('Choose a duration from 1m to 365d, for example 5m or 2h.') from None
            if seconds<60:
                raise TemporaryPromotionInputError('Choose a duration from 1m to 365d.')
            if type(uid) is not int or not 0<uid<2**63 or uid==user.id:
                raise TemporaryPromotionInputError('Choose another personal member.')
            me=await asyncio.wait_for(client.get_me(),5)
            if uid==me.id:
                raise TemporaryPromotionInputError('I cannot promote myself.')
            async def check():
                await owner()
                bot=await asyncio.wait_for(client.get_chat_member(chat.id,me.id),5)
                member=await asyncio.wait_for(client.get_chat_member(chat.id,uid),5)
                if (bot.status!=ChatMemberStatus.ADMINISTRATOR or getattr(getattr(bot,'privileges',None),'can_promote_members',False) is not True):
                    raise TemporaryPromotionInputError('I need Add administrators permission.')
                if member.status!=ChatMemberStatus.MEMBER:
                    raise TemporaryPromotionInputError('Target must be an unrestricted member, not an existing admin.')
                return bot
            bot=await check()
            rights={key:bool(getattr(bot.privileges,key,False)) for key in RIGHTS}
            if not rights.get('can_manage_chat'):
                raise TemporaryPromotionInputError('Bot management rights could not be verified.')
            expires=datetime.now(timezone.utc)+timedelta(seconds=seconds)
            request=await reserve(db,chat.id,uid,actor=user.id,bot=me.id,expires=expires,rights=rights)
            final=await check()
            if any(bool(getattr(final.privileges,key,False))!=value for key,value in rights.items()):
                raise TemporaryPromotionInputError('Bot rights changed. No promotion attempted.')
            fields={key:False for key in inspect.signature(ChatPrivileges).parameters}
            fields.update(rights)
            dispatched=True
            ack=await asyncio.wait_for(client.promote_chat_member(chat.id,uid,privileges=ChatPrivileges(**fields)),15)
            if ack is not True:
                raise PromotionError('Telegram promotion unconfirmed.')
            await finish(db,request,'active',expected='prepared')
            await reply(message,panel('Temporary promotion saved',table=kv_table([
                ('Member',str(uid)),('Until',expires.strftime('%d %b %H:%M UTC')),('Request',request)]),
                note='Limited rights only. Expiry needs the bot online with admin rights. Changed or uncertain state stops for review. /tpromote status'))
        except (TemporaryPromotionInputError,PromotionError) as error:
            if request is not None and dispatched:
                try:
                    await finish(ctx.db,request,'review',expected='prepared')
                except Exception:
                    logging.getLogger(__name__).warning('#Errors Temporary promotion outcome needs inspection')
            if request is not None and not dispatched:
                try:
                    await finish(ctx.db,request,'cancelled',expected='prepared')
                except Exception:
                    logging.getLogger(__name__).warning('#Errors Temporary promotion cancellation unconfirmed')
            await reply(message,html.escape(str(error)) if not dispatched else 'Promotion or tracking unconfirmed. Check Telegram and /tpromote status; no automatic retry.')
        except Exception as error:
            if request is not None:
                try:
                    await finish(ctx.db,request,'review' if dispatched else 'cancelled',expected='prepared')
                except Exception:
                    logging.getLogger(__name__).warning('#Errors Temporary promotion tracking needs inspection')
            logging.getLogger(__name__).warning('#Errors Temporary promotion unavailable (%s)',type(error).__name__)
            await reply(message,'Promotion or tracking unconfirmed. Check Telegram and /tpromote status before retrying.')
    return tpromote


def build_tagging_settings(ctx):
    """Settings/statistics and self-service consent, not a mass-mention sender."""
    from pyrogram.types import InlineKeyboardButton as Button,InlineKeyboardMarkup as Keyboard
    from ...platform.group_tagging import operate,TagError
    from ...ui.tables import kv_table

    def identity(user):
        uid=getattr(user,'id',None)
        return type(uid) is int and 0<uid<2**63 and not getattr(user,'is_bot',False)

    async def authority(client,message):
        if (getattr(getattr(message,'chat',None),'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or not identity(getattr(message,'from_user',None)) or getattr(message,'sender_chat',None) is not None):
            raise TagError('Use your personal administrator account in a group.')
        if not await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5):
            raise TagError('Current Manage chat permission required.')

    def handler(command):
        async def call(client,message):
            committed=False
            try:
                await authority(client,message)
                args=(getattr(message,'text','') or '').lower().split()[1:]
                if (command=='tagstats' and args) or (command=='allsettings' and args not in ([],['on'],['off'])):
                    raise TagError('Use /allsettings on|off or /tagstats.')
                enabled=None if not args else args[0]=='on'
                await authority(client,message)
                state=await operate(getattr(ctx,'db',None),message.chat.id,enabled=enabled,actor=message.from_user.id if enabled is not None else None)
                committed=enabled is not None
                await authority(client,message)
                keyboard=Keyboard([[Button('Join mentions',callback_data=f'tagopt:{message.chat.id}:join'),Button('Leave mentions',callback_data=f'tagopt:{message.chat.id}:leave')]])
                await reply(message,panel('Mention settings' if command=='allsettings' else 'Mention statistics',
                    table=kv_table([('Opt-in mentions','On' if state['enabled'] else 'Off'),('Joined members',str(state['count'])),('Status','Saved' if committed else 'Current')]),
                    note='Members choose below. Turning off clears all opt-ins. Limit: 500. Sending mention batches is not available yet.'),reply_markup=keyboard)
            except TagError as error:
                await reply(message,'Settings saved; details withheld.' if committed else str(error))
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Mention settings unavailable (%s)',type(error).__name__)
                await reply(message,'Settings saved; display unconfirmed.' if committed else 'Mention settings unconfirmed. Try /allsettings before retrying.')
        return call

    async def press(client,query,rest):
        saved=False
        try:
            user=getattr(query,'from_user',None)
            chat=getattr(getattr(query,'message',None),'chat',None)
            parts=rest.split(':')
            if (len(parts)!=2 or getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or not identity(user) or parts[0]!=str(chat.id) or parts[1] not in ('join','leave')):
                raise TagError('Invalid mention control.')
            joining=parts[1]=='join'
            if joining:
                async def member():
                    current=await asyncio.wait_for(client.get_chat_member(chat.id,user.id),5)
                    return current.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.MEMBER) or (current.status==ChatMemberStatus.RESTRICTED and getattr(current,'is_member',False) is True)
                if not await member() or not await member():
                    raise TagError('Current group membership required to join mentions.')
            # Leaving withdraws consent even if the caller has already left the group.
            await operate(getattr(ctx,'db',None),chat.id,join=joining,user=user.id)
            saved=True
            await query.answer('You joined mentions.' if joining else 'You left mentions.',show_alert=True)
        except TagError as error:
            await query.answer(str(error),show_alert=True)
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Mention opt-in unavailable (%s)',type(error).__name__)
            await query.answer('Choice saved; display unconfirmed.' if saved else 'Choice unconfirmed. No automatic retry.',show_alert=True)

    router=getattr(ctx,'actions',None)
    if router is not None and not router.handles('tagopt:x'):
        router.register('tagopt',press)
    return {command:handler(command) for command in ('allsettings','tagstats')}
