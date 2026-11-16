"""Post-dispatch cleanup for recognized commands only; no passive deletion."""

import html
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
                or actor <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use command-cleaning controls as yourself inside a group."
                )
                return
            if not await is_moderator(client, message, need="can_delete_messages"):
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
                state = await operate(
                    ctx,
                    message.chat.id,
                    enabled,
                    actor=actor if enabled is not None else None,
                )
                await reply(
                    message,
                    panel(
                        "Command-message cleaning",
                        table=kv_table(
                            [("Recognized commands", "On" if state else "Off")]
                        ),
                        note="Deletes the incoming command after its handler returns, not the bot response. Applies to / ! . ? and all senders, including permission-denied responses. Unknown commands and other bots are untouched; admin/user/other categories remain pending. Private chats are never cleaned. Requires my Delete messages right.",
                    ),
                )
            except CleaningError as error:
                await reply(message, html.escape(str(error)))

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
