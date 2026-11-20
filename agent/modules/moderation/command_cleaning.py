"""Post-dispatch cleanup for recognized commands only; no passive deletion."""

import html
import asyncio
import logging
from functools import wraps
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.command_cleaning import operate, CleaningError
from ...platform.admin_settings import denied
from ...utils.rich import reply
from ...ui.tables import panel, kv_table

logger = logging.getLogger(__name__)
GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


def build(ctx):
    from . import is_moderator

    def handler(command):
        async def call(client, message):
            actor = getattr(getattr(message, "from_user", None), "id", None)
            if (
                getattr(getattr(message, "chat", None), "type", None) not in GROUPS
                or type(actor) is not int
                or not 0 < actor < 2**63
                or getattr(getattr(message, "from_user", None), "is_bot", False)
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use command-cleaning controls as yourself inside a group."
                )
                return
            async def authorized():
                return await asyncio.wait_for(is_moderator(client, message, need="can_delete_messages"), 5)

            try:
                allowed = await authorized()
            except Exception:
                await reply(message, "Permissions unavailable. No setting change attempted.")
                return
            if not allowed:
                await denied(
                    ctx,
                    message,
                    "You need Delete messages permission to manage command cleaning.",
                )
                return
            args = (getattr(message, "text", "") or "").lower().split()[1:]
            try:
                enabled = None
                if args:
                    if len(args) != 1 or args[0] not in (
                        "all",
                        "on",
                        "off",
                        "yes",
                        "no",
                    ):
                        raise CleaningError(
                            "Usage: /cleancommand all|on|off or /keepcommand all. Admin/user/other categories are not supported yet."
                        )
                    enabled = (
                        False
                        if command == "keepcommand"
                        else args[0] in ("all", "on", "yes")
                    )
                if enabled is not None and not await authorized():
                    await reply(message, "Administrator permissions changed. No setting change attempted.")
                    return
                state = await operate(
                    ctx,
                    message.chat.id,
                    enabled,
                    actor=actor if enabled is not None else None,
                )
                if not await authorized():
                    await reply(message, "Administrator permissions changed. Setting saved; details withheld." if enabled is not None else "Administrator permissions changed. Settings withheld.")
                    return
                await reply(
                    message,
                    panel(
                        "Command-message cleaning",
                        table=kv_table(
                            [("Command deletion", "On" if state else "Off"),
                             ("Moderator", str(actor)),
                             ("Status", "Saved" if enabled is not None else "Current setting")]
                        ),
                        note="Deletes recognized command messages after handling—not bot replies. All senders included, even denied commands. Prefixes: / ! . # $ % & ?\nUnknown commands, other bots and private chats are untouched. Needs my Delete messages right.\n/cleancommand on|off · /keepcommand all · No arguments: view setting.",
                    ),
                )
            except CleaningError as error:
                await reply(message, html.escape(str(error)))
            except Exception as error:
                logger.warning("#Errors Command-cleaning settings unavailable (%s)", type(error).__name__)
                await reply(message, "Setting or permissions unconfirmed. Check /cleancommand before retrying.")

        return call

    return {command: handler(command) for command in ("cleancommand", "keepcommand")}


def wrap(ctx, handler):
    """Place outside the plugin gate: a handled denial is still a command.

    Never delete on an unhandled exception: preserve evidence for diagnosis.
    Cleanup outages must not hide a handler result or change its permissions.
    """

    @wraps(handler)
    async def call(client, message):
        result = await handler(client, message)
        if getattr(getattr(message, "chat", None), "type", None) not in GROUPS:
            return result
        try:
            if not await operate(ctx, message.chat.id):
                return result
            me = await client.get_me()
            member = await client.get_chat_member(message.chat.id, me.id)
            if member.status != ChatMemberStatus.OWNER and not (
                member.status == ChatMemberStatus.ADMINISTRATOR
                and getattr(
                    getattr(member, "privileges", None), "can_delete_messages", False
                )
            ):
                return result
            if await client.delete_messages(message.chat.id, message.id) is not True:
                logger.warning(
                    "Command-message deletion unconfirmed; no retry attempted."
                )
        except Exception:
            logger.warning(
                "Command cleanup unavailable or deletion unconfirmed; no retry attempted."
            )
        return result

    return call
