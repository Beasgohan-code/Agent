"""Administrator commands; mutations always authorize against live Telegram state."""

import html
from pyrogram.enums import ChatMemberStatus, ChatType, ChatMembersFilter
from pyrogram.types import ChatPrivileges
from ...platform.admin_settings import options, denied, AdminStateError
from ...ui.tables import panel, Table
from ...utils.rich import reply
from ..moderation import is_moderator

COMMANDS = ("promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror")
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
                    if user is not None:
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
            target = await resolve(client, message)
            target_id = getattr(target, "id", None)
            if type(target_id) is not int or not 0 < target_id < 2**63:
                raise ValueError("Invalid user identity.")
            me = await client.get_me()
            if target_id in (user.id, me.id):
                raise ValueError(
                    "You cannot change your own or my administrator privileges here."
                )
            bot = await client.get_chat_member(chat.id, me.id)
            caller = await client.get_chat_member(chat.id, user.id)
            member = await client.get_chat_member(chat.id, target_id)
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
            result = await client.promote_chat_member(
                chat.id, target_id, privileges=privileges
            )
            if result is not True:
                raise ValueError(
                    "Telegram did not confirm the administrator change. Check current rights before retrying."
                )
            snapshots.pop(chat.id, None)
            ctx.chats.log(chat.id, command, actor_id=user.id, target_id=target_id)
            await reply(
                message,
                f"User <code>{target_id}</code> {'promoted' if command == 'promote' else 'demoted'}.",
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

    return {command: handler(command) for command in COMMANDS}
