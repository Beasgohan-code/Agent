"""Administrator commands; mutations always authorize against live Telegram state."""

import html
import asyncio
import logging
import re
import unicodedata
from pyrogram.enums import ChatMemberStatus, ChatType, ChatMembersFilter
from pyrogram.types import ChatPrivileges
from ...platform.admin_settings import options, denied, AdminStateError
from ...platform.commands import replied_message,ReplyTargetError
from ...ui.tables import panel
from ...utils.rich import reply
from ..moderation import is_moderator

COMMANDS = ("etagall", "eall", "tagall", "all", "tagabort", "allsettings", "tagstats", "tpromote", "promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror")
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


class AdminInputError(ValueError):
    """Safe locally authored input/permission failure, never provider text."""


def mentioned_target(message):
    """Bind a Telegram text mention to the first argument using UTF-16 spans."""
    mentions = [entity for entity in getattr(message, 'entities', None) or []
                if getattr(entity, 'user', None) is not None]
    if not mentions:
        return None
    text = getattr(message, 'text', '') or ''
    parts = text.split(maxsplit=1)
    if len(mentions) != 1 or len(parts) != 2:
        raise AdminInputError('Provide one text mention as the target argument.')
    entity = mentions[0]
    tail = parts[1]
    prefix = text[:len(text) - len(tail)]
    offset, length = getattr(entity, 'offset', None), getattr(entity, 'length', None)
    if (type(offset) is not int or offset != len(prefix.encode('utf-16-le')) // 2
            or type(length) is not int or length <= 0):
        raise AdminInputError('Text mention must cover the target argument.')
    encoded = tail.encode('utf-16-le')
    if length * 2 > len(encoded):
        raise AdminInputError('Text mention span is invalid.')
    try:
        label = encoded[:length * 2].decode('utf-16-le')
        remainder = encoded[length * 2:].decode('utf-16-le')
    except UnicodeDecodeError:
        raise AdminInputError('Text mention span is invalid.') from None
    if not label.strip() or (remainder and not remainder[0].isspace()):
        raise AdminInputError('Text mention must cover the complete target name.')
    return entity.user, remainder.strip()


async def resolve(client, message):
    source=await replied_message(client,message)
    args=(getattr(message,'text','') or '').split()
    if source is not None:
        if (getattr(getattr(source,'chat',None),'id',None)!=message.chat.id
                or getattr(source,'sender_chat',None) is not None):
            raise AdminInputError('Reply to a personal member from this group.')
        target=getattr(source,'from_user',None)
        if target is None or len(args)!=1:
            raise AdminInputError('Reply to a personal member without an additional target.')
        return target
    mention = mentioned_target(message)
    if mention is not None:
        target, remainder = mention
        if remainder:
            raise AdminInputError('Provide one target without additional arguments.')
        return target
    if len(args)!=2:
        raise AdminInputError('Reply to a user or provide a username, mention or user ID.')
    value=args[1]
    if value.isascii() and value.isdecimal() and len(value)<=19 and 0<int(value)<2**63:
        value=int(value)
    elif not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',value):
        raise AdminInputError('Use a positive user ID or @username.')
    return await asyncio.wait_for(client.get_users(value),5)


async def promotion_target(client,message):
    """Parse title only for promotion; other consumers keep strict target syntax."""
    parts=(getattr(message,'text','') or '').split(maxsplit=1)
    tail=parts[1] if len(parts)==2 else ''
    source=await replied_message(client,message)
    if source is not None:
        if getattr(getattr(source,'chat',None),'id',None)!=message.chat.id:
            raise AdminInputError('Reply to a member from this group.')
        target=getattr(source,'from_user',None)
        if target is None or getattr(source,'sender_chat',None) is not None:
            raise AdminInputError('Reply to a personal member identity.')
        title=tail
        value=None
    else:
        mention = mentioned_target(message)
        if mention is not None:
            target, title = mention
            value = None
        else:
            args=tail.split(maxsplit=1)
            if not args:
                raise AdminInputError('Usage: /promote @username|positive_ID [title], or reply /promote [title].')
            value=args[0]
            title=args[1] if len(args)==2 else ''
            if value.isascii() and value.isdecimal() and len(value)<=19 and 0<int(value)<2**63:
                value=int(value)
            elif not re.fullmatch(r'@[A-Za-z0-9_]{1,32}',value):
                raise AdminInputError('Use a positive user ID or @username, or reply to a member.')
            target=None
    if len(title)>16 or any(unicodedata.category(char).startswith('C') for char in title):
        raise AdminInputError('Administrator title must be 1–16 characters with no control/format characters. Omit it for no custom title. Telegram may reject emoji titles.')
    if target is None:
        target=await asyncio.wait_for(client.get_users(value),5)
    return target,title


def build(ctx):
    class SnapshotInputError(ValueError):
        """Safe command validation, distinct from provider failures."""

    async def admincache(client,message):
        try:
            chat=getattr(message,'chat',None)
            user=getattr(message,'from_user',None)
            if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                    or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                    or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                raise SnapshotInputError('Use your personal administrator account inside the group.')
            if len((getattr(message,'text','') or '').split())!=1:
                raise SnapshotInputError('Usage: /admincache')
            async def authority():
                if not await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5):
                    raise SnapshotInputError('Current Manage chat administrator permission required. Snapshot withheld.')
            await authority()
            ids=set()
            truncated=False
            async def collect():
                nonlocal truncated
                raw=0
                async for record in client.get_chat_members(chat.id,filter=ChatMembersFilter.ADMINISTRATORS,limit=201):
                    raw+=1
                    if raw>200:
                        truncated=True
                        break
                    uid=getattr(getattr(record,'user',None),'id',None)
                    if type(uid) is int and 0<uid<2**63 and record.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR):
                        ids.add(uid)
            await asyncio.wait_for(collect(),15)
            await authority()
            await reply(message,panel('Administrator snapshot',lines=[
                f'Live snapshot checked: {len(ids)} distinct administrators returned.',
                'Bounded to the first 200 returned records; more may exist.' if truncated else 'Based on the current Telegram response.',
            ],note='Permission checks are not cached. No administrator identities are stored by this command.'))
        except SnapshotInputError as error:
            await reply(message,str(error))
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Administrator snapshot unavailable (%s)',type(error).__name__)
            await reply(message,'Administrator snapshot unavailable. No partial result displayed.')

    class OptionInputError(ValueError):
        """Locally authored administrator-option validation."""

    def option_handler(command):
        async def call(client,message):
            committed=False
            try:
                chat=getattr(message,'chat',None)
                user=getattr(message,'from_user',None)
                if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise OptionInputError('Use your personal administrator account inside the group.')
                args=(getattr(message,'text','') or '').split()[1:]
                if len(args)>1 or args and args[0].lower() not in ('yes','no','on','off'):
                    raise OptionInputError(f'Usage: /{command} yes|no|on|off; omit the value to view.')
                async def authority():
                    return await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5)
                if not await authority():
                    await denied(ctx,message,'Current Manage chat administrator permission required.')
                    return
                if args:
                    if not await authority():
                        raise OptionInputError('Administrator permission changed. No setting change requested.')
                    state=await options(ctx,chat.id,setting=command,enabled=args[0].lower() in ('yes','on'),actor=user.id)
                    committed=True
                else:
                    state=await options(ctx,chat.id)
                if not await authority():
                    raise OptionInputError('Setting saved; current administrator permission changed. Details withheld.' if committed else 'Current administrator permission changed. Setting withheld.')
                warning=('\nWarning: anonymous group senders can bypass granular group permission checks. Personal-identity and Owner-only safeguards still apply.' if command=='anonadmin' else '')
                await reply(message,f"{command}: {'on' if state[command] else 'off'}{warning}")
            except (OptionInputError,AdminStateError) as error:
                await reply(message,str(error))
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Administrator option unavailable (%s)',type(error).__name__)
                await reply(message,'Setting saved; confirmation or current permissions unavailable. Details withheld.' if committed else 'Administrator setting unavailable or result unconfirmed. Refresh before retrying.')
        return call

    async def run(client, message, command):
        chat = getattr(message, "chat", None)
        if getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await reply(message, "Use administrator commands inside a group.")
            return
        confirmed=False
        try:
            user = getattr(message, "from_user", None)
            # Settings and privilege changes require accountable personal identity.
            if (
                type(getattr(user, "id", None)) is not int
                or not 0<user.id<2**63
                or getattr(user,"is_bot",False)
                or getattr(message, "sender_chat", None) is not None
            ):
                raise AdminInputError(
                    "Use your personal identity for administrator changes."
                )
            need = (
                "can_promote_members"
                if command in ("promote", "demote")
                else "can_manage_chat"
            )
            if not await asyncio.wait_for(is_moderator(client, message, need=need),5):
                await denied(
                    ctx, message, "You do not have the required group-admin permission."
                )
                return
            title = ""
            if command == "promote":
                target, title = await promotion_target(client, message)
            else:
                target = await resolve(client, message)
            target_id = getattr(target, "id", None)
            if type(target_id) is not int or not 0 < target_id < 2**63:
                raise AdminInputError("Invalid user identity.")
            me = await asyncio.wait_for(client.get_me(),5)
            if target_id in (user.id, me.id):
                raise AdminInputError(
                    "You cannot change your own or my administrator privileges here."
                )
            if not await asyncio.wait_for(is_moderator(client,message,need='can_promote_members'),5):
                raise AdminInputError('Your Add administrators permission changed. No administrator change requested.')
            # The final grant ceiling and protected-target checks use fresh records,
            # after the final moderator probe, with no further reads before mutation.
            bot,caller,member=await asyncio.gather(*(
                asyncio.wait_for(client.get_chat_member(chat.id,uid),5)
                for uid in (me.id,user.id,target_id)
            ))
            if bot.status != ChatMemberStatus.ADMINISTRATOR or not getattr(
                getattr(bot, "privileges", None), "can_promote_members", False
            ):
                raise AdminInputError("I need the Add administrators permission.")
            if caller.status != ChatMemberStatus.OWNER and (
                caller.status != ChatMemberStatus.ADMINISTRATOR
                or not getattr(
                    getattr(caller, "privileges", None), "can_promote_members", False
                )
            ):
                raise AdminInputError(
                    "Your Add administrators permission is no longer available."
                )
            if member.status == ChatMemberStatus.OWNER:
                raise AdminInputError("The group owner cannot be changed here.")
            if command == "promote" and member.status == ChatMemberStatus.ADMINISTRATOR:
                raise AdminInputError(
                    "This user is already an administrator; no privileges changed."
                )
            if command == "promote" and member.status != ChatMemberStatus.MEMBER:
                raise AdminInputError(
                    "The user must be an unrestricted member of this group first."
                )
            if command == "demote" and member.status != ChatMemberStatus.ADMINISTRATOR:
                raise AdminInputError("This user is not an administrator.")
            if command == "demote" and not getattr(member, "can_be_edited", False):
                raise AdminInputError(
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
            result = await asyncio.wait_for(client.promote_chat_member(
                chat.id, target_id, privileges=privileges
            ),10)
            if result is not True:
                raise AdminInputError(
                    "Telegram did not confirm the administrator change. Check current rights before retrying."
                )
            confirmed=True
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
        except (AdminInputError, AdminStateError, ReplyTargetError) as error:
            await reply(message, html.escape(str(error)))
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Administrator change unavailable (%s)',type(error).__name__)
            await reply(message,'Administrator change confirmed; response details unavailable. Inspect current rights before retrying.' if confirmed else
                'Telegram administrator operation could not be confirmed. Check current rights before retrying.')

    def handler(command):
        async def call(client, message):
            await run(client, message, command)

        return call

    return {**{command: handler(command) for command in COMMANDS if command not in ("anonadmin", "adminerror", "admincache", "adminlist", "tpromote", "allsettings", "tagstats", "tagall", "all", "tagabort", "etagall", "eall")}, "anonadmin": option_handler("anonadmin"), "adminerror": option_handler("adminerror"), "admincache": admincache, "tpromote": build_tpromote(ctx), **build_tagging_settings(ctx), **build_tag_runs(ctx)}


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
    """Group mention information; no enrollment or enable switch."""
    from ...platform.group_tagging import run_summary,TagError
    from ...ui.tables import kv_table

    async def handler(client,message):
        try:
            user=getattr(message,'from_user',None)
            chat=getattr(message,'chat',None)
            async def authority():
                if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                        or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                        or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
                    raise TagError('Use your personal group administrator account.')
                if not await asyncio.wait_for(is_moderator(client,message,need='can_manage_chat'),5):
                    raise TagError('Current Manage chat permission required.')
            await authority()
            if len((getattr(message,'text','') or '').split())!=1:
                raise TagError('Mentions are always available. No on/off or joining needed.')
            summary=await run_summary(getattr(ctx,'db',None),chat.id,actor=user.id)
            await authority()
            await reply(message,panel('Group mention info',table=kv_table([
                ('Mentions','Always available'),('Batch size','20'),('Pause','5 seconds'),
                ('Last snapshot',str(summary['total'])),('Scanned',str(summary['cursor'])),('Run',summary['state'])]),
                note='@all · @eall · /tagabort\nNo joining needed. Uses members Telegram returns, which may be incomplete. Snapshot cap: 2000.'))
        except TagError as error:
            await reply(message,str(error))
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Mention info unavailable (%s)',type(error).__name__)
            await reply(message,'Mention information unavailable.')
    async def retired(client,query,rest):
        await query.answer('No joining needed anymore. An admin can use @all or @eall.',show_alert=True)
    router=getattr(ctx,'actions',None)
    if router is not None and not router.handles('tagopt:x'):
        router.register('tagopt',retired)
    return {'allsettings':handler,'tagstats':handler}


def build_tag_runs(ctx):
    """Retrieved-member mention jobs, durable cursor, authorized Resume/Stop."""
    from ...platform.group_tagging import start_run,claim_batch,settle_batch,stop_run,eligible,TagError
    from pyrogram.types import InlineKeyboardMarkup as Keyboard,InlineKeyboardButton as Button
    from pyrogram.enums import ParseMode
    from types import SimpleNamespace

    async def authorized(client,message,user=None):
        user=user or getattr(message,'from_user',None)
        chat=getattr(message,'chat',None)
        if (getattr(chat,'type',None) not in (ChatType.GROUP,ChatType.SUPERGROUP)
                or type(getattr(user,'id',None)) is not int or not 0<user.id<2**63
                or getattr(user,'is_bot',False) or getattr(message,'sender_chat',None) is not None):
            raise TagError('Use your personal group administrator account.')
        if not await asyncio.wait_for(is_moderator(client,SimpleNamespace(chat=chat,from_user=user),need='can_manage_chat'),5):
            raise TagError('Current Manage chat administrator permission required.')
        return user

    running={}

    async def report(message,request,state,sent,scanned,total,detail=''):
        rows=[]
        if state=='paused':
            rows.append([Button('Resume',callback_data=f'tagrun:{request}:resume')])
        if state in ('paused','review','sending','running'):
            rows.append([Button('Stop',callback_data=f'tagrun:{request}:stop')])
        await reply(message,panel('Group mentions',lines=[f'{sent} mentions acknowledged · {state}',f'Scanned {scanned}/{total} retrieved members',detail] if detail else [f'{sent} mentions acknowledged · {state}',f'Scanned {scanned}/{total} retrieved members'],
            note='20 per message · 5s pause. Telegram may return only part of the group. Stop cannot recall an in-flight message.'),reply_markup=Keyboard(rows) if rows else None)

    async def batch(client,message,request,user):
        from pyrogram.errors import FloodWait
        import secrets
        await authorized(client,message,user)
        db=getattr(ctx,'db',None)
        chunk=await claim_batch(db,message.chat.id,request,actor=user.id)
        confirmed=False
        sent=0
        labels={}
        try:
            if chunk['source']!='group':
                raise TagError('Old opt-in run. Use /tagabort, then start @all again.')
            members=[]
            for uid in chunk['members']:
                member=await asyncio.wait_for(client.get_chat_member(message.chat.id,uid),5)
                if member.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.MEMBER) or (member.status==ChatMemberStatus.RESTRICTED and getattr(member,'is_member',False) is True):
                    members.append(uid)
                    person=getattr(member,'user',None)
                    name=getattr(person,'first_name',None) or getattr(person,'username',None) or '👤'
                    labels[uid]=html.escape(str(name)[:48])
            await authorized(client,message,user)
            members=await eligible(db,message.chat.id,request,members)
            if members:
                emojis=('🌟','🌸','🍀','🌻','🦋','🌺','🍁','🪷')
                body=(html.escape(chunk['mention_text'])+'\n' if chunk['mention_text'] else '')+' '.join(f'<a href="tg://user?id={uid}">{secrets.choice(emojis) if chunk["style"]=="emoji" else labels[uid]}</a>' for uid in members)
                result=await asyncio.wait_for(client.send_message(chat_id=message.chat.id,text=body,parse_mode=ParseMode.HTML),15)
                if type(getattr(result,'id',None)) is not int or result.id<=0:
                    raise TagError('Mention delivery unconfirmed. No batch retried.')
                sent=len(members)
            confirmed=True
        except FloodWait as error:
            seconds=max(1,int(error.value))
            async with db._pool.acquire(timeout=5) as conn:
                await conn.execute("UPDATE agent_tag_runs SET last_attempt_at=now()+$4*interval '1 second' WHERE tenant=$1 AND group_id=$2 AND id=$3",db.scope,message.chat.id,request,seconds,timeout=5)
            raise TagError(f'Telegram requested a {seconds}s wait. Run stopped for review; no batch retried.') from None
        finally:
            state=await settle_batch(db,message.chat.id,request,confirmed=confirmed)
        return state,sent,chunk['cursor'],chunk['total']

    async def launch(client,message,request,user):
        key=(message.chat.id,request)
        for old,job in list(running.items()):
            if job.finished:
                running.pop(old,None)
        if key in running:
            raise TagError('This run is already active.')
        async def runner(job):
            sent=scanned=total=0
            try:
                while True:
                    state,count,scanned,total=await batch(client,message,request,user)
                    sent+=count
                    job.progress=scanned/max(1,total)
                    job.detail=f'{sent} mentions acknowledged'
                    if state!='paused':
                        return
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Group mention run paused (%s)',type(error).__name__)
                async with ctx.db._pool.acquire(timeout=5) as conn:
                    row=await conn.fetchrow('SELECT state,cursor,total FROM agent_tag_runs WHERE tenant=$1 AND group_id=$2 AND id=$3',ctx.db.scope,message.chat.id,request,timeout=5)
                state=row['state'] if row else 'stopped'
                await report(message,request,state,sent,row['cursor'] if row else scanned,row['total'] if row else total,
                    str(error) if isinstance(error,TagError) else 'Delivery or permissions unconfirmed. No automatic retry; use /tagabort.')
            finally:
                running.pop(key,None)
        if getattr(ctx,'jobs',None) is None:
            raise TagError('Mention worker unavailable. No message sent.')
        running[key]=ctx.jobs.submit('group',user.id,runner,label='Group mentions')

    async def stop_local(group,request=None):
        for key,job in list(running.items()):
            if key[0]==group and (request is None or key[1]==request):
                ctx.jobs.cancel(job.id)

    def handler(command):
        async def call(client,message):
            try:
                user=await authorized(client,message)
                parts=(getattr(message,'text','') or '').split(maxsplit=1)
                mention_text=parts[1].strip() if len(parts)>1 else ''
                if len(mention_text)>500:
                    raise TagError('Keep the optional mention message within 500 characters.')
                if command=='tagabort':
                    if mention_text:
                        raise TagError('Use /tagabort without extra arguments.')
                    await stop_run(getattr(ctx,'db',None),message.chat.id,actor=user.id)
                    await stop_local(message.chat.id)
                    await reply(message,'Mention run stopped. An in-flight message may still arrive.')
                    return
                members=[]
                seen=set()
                raw=0
                async def collect():
                    nonlocal raw
                    async for record in client.get_chat_members(message.chat.id,limit=2001):
                        raw+=1
                        if raw>2000:
                            break
                        person=getattr(record,'user',None)
                        uid=getattr(person,'id',None)
                        if (type(uid) is int and 0<uid<2**63 and uid not in seen
                                and not getattr(person,'is_bot',False) and not getattr(person,'is_deleted',False)
                                and (record.status in (ChatMemberStatus.OWNER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.MEMBER) or (record.status==ChatMemberStatus.RESTRICTED and getattr(record,'is_member',False) is True))):
                            seen.add(uid)
                            members.append(uid)
                await asyncio.wait_for(collect(),60)
                await authorized(client,message)
                if not members:
                    raise TagError('Telegram returned no eligible members. Check my member-list access.')
                request=await start_run(getattr(ctx,'db',None),message.chat.id,actor=user.id,style='emoji' if command in ('etagall','eall') else 'plain',members=members,mention_text=mention_text)
                await launch(client,message,request,user)
            except TagError as error:
                await reply(message,str(error))
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors Group mention admission unavailable (%s)',type(error).__name__)
                await reply(message,'Member retrieval or run admission unconfirmed. No automatic retry; use /tagabort before retrying.')
        return call

    async def press(client,query,rest):
        try:
            user=await authorized(client,query.message,query.from_user)
            parts=rest.split(':')
            if len(parts)!=2 or not re.fullmatch('[0-9a-f]{32}',parts[0]) or parts[1] not in ('resume','stop'):
                raise TagError('Invalid mention control.')
            request,action=parts
            if action=='stop':
                await authorized(client,query.message,user)
                await stop_run(getattr(ctx,'db',None),query.message.chat.id,actor=user.id,request=request)
                await stop_local(query.message.chat.id,request)
                await query.answer('Stopped. An in-flight message may still arrive.',show_alert=True)
            else:
                async with ctx.db._pool.acquire(timeout=5) as conn:
                    row=await conn.fetchrow('SELECT state,source FROM agent_tag_runs WHERE tenant=$1 AND group_id=$2 AND id=$3',ctx.db.scope,query.message.chat.id,request,timeout=5)
                if row is None or row['state']!='paused' or row['source']!='group':
                    raise TagError('Run is closed, uncertain or outdated. Use /tagabort, then start again.')
                await launch(client,query.message,request,user)
                await query.answer('Resumed.')
        except TagError as error:
            await query.answer(str(error),show_alert=True)
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Mention control unavailable (%s)',type(error).__name__)
            await query.answer('Mention action unconfirmed. Use /tagabort; no automatic retry.',show_alert=True)

    router=getattr(ctx,'actions',None)
    if router is not None and not router.handles('tagrun:x'):
        router.register('tagrun',press)
    return {command:handler(command) for command in ('tagall','all','tagabort','etagall','eall')}
