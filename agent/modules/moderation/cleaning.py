"""Explicit allowlist of group service events; never delete user content."""

import html
import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.service_cleaning import operate, KINDS, CleaningError
from ...platform.admin_settings import denied
from ...utils.rich import reply
from ...ui.tables import panel, kv_table

logger = logging.getLogger(__name__)
SERVICES = {
    "new_chat_members": "joins",
    "left_chat_members": "leaves",
    "left_chat_member": "leaves",
    "pinned_message": "pins",
    "new_chat_title": "title",
    "new_chat_photo": "photo",
    "delete_chat_photo": "photo",
    "video_chat_started": "videochat",
    "video_chat_ended": "videochat",
    "video_chat_scheduled": "videochat",
    "video_chat_members_invited": "videochat",
}
GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


def build(ctx):
    from . import is_moderator

    async def cleanservice(client, message):
        user = getattr(message, "from_user", None)
        if (
            getattr(getattr(message, "chat", None), "type", None) not in GROUPS
            or type(getattr(user, "id", None)) is not int
            or user.id <= 0
            or getattr(message, "sender_chat", None) is not None
        ):
            await reply(message, "Use /cleanservice as yourself inside a group.")
            return
        if not await is_moderator(client, message, need="can_delete_messages"):
            await denied(
                ctx,
                message,
                "You need Delete messages permission to manage service cleaning.",
            )
            return
        args = (getattr(message, "text", "") or "").lower().split()[1:]
        try:
            if not args:
                kinds = None
            elif args in (["on"], ["yes"], ["all"]):
                kinds = list(KINDS)
            elif args in (["off"], ["no"], ["none"]):
                kinds = []
            else:
                kinds = args
            state = await operate(
                ctx,
                message.chat.id,
                kinds,
                actor=user.id if kinds is not None else None,
            )
            await reply(
                message,
                panel(
                    "Service-message cleaning",
                    table=kv_table(
                        [(kind, "On" if kind in state else "Off") for kind in KINDS]
                    ),
                    note="Use /cleanservice on|off, or replace the selection with /cleanservice joins leaves pins title photo videochat. Ordinary messages, payments, migration and topic events are never selected. Requires my Delete messages right. Deleting a pin notice does not unpin the message. Other join/leave automation still runs.",
                ),
            )
        except CleaningError as error:
            await reply(message, html.escape(str(error)))

    return {"cleanservice": cleanservice}


async def clean(ctx, client, message):
    if getattr(getattr(message, "chat", None), "type", None) not in GROUPS:
        return False
    service = getattr(message, "service", None)
    kind = SERVICES.get(getattr(service, "value", None))
    if kind is None:
        return False
    try:
        if kind not in await operate(ctx, message.chat.id):
            return False
        me = await client.get_me()
        member = await client.get_chat_member(message.chat.id, me.id)
        if member.status != ChatMemberStatus.OWNER and not (
            member.status == ChatMemberStatus.ADMINISTRATOR
            and getattr(
                getattr(member, "privileges", None), "can_delete_messages", False
            )
        ):
            return False
        confirmed = await client.delete_messages(message.chat.id, message.id)
        if confirmed is not True:
            logger.warning("Service notice deletion unconfirmed; no retry attempted.")
            return False
        return True
    except Exception:
        logger.warning(
            "Service cleaning unavailable or deletion unconfirmed; no retry attempted."
        )
        return False
