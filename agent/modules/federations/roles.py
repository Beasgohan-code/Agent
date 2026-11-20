"""Private recipient consent for federation administrator and ownership changes."""

import html
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.types import (
    InlineKeyboardMarkup as Keyboard,
)
from ...platform.federation_roles import change, FederationError
from ...utils.rich import reply, send
from ..group.admin import resolve

COMMANDS = ("fedpromote", "feddemote", "feddemoteme", "fedtransfer")
PREFIX = "fedrole"


def invitation_keyboard(theme, invitation):
    return Keyboard([
        [theme.button('Accept', icon='check', callback_data=f'{PREFIX}:accept:{invitation}', style=ButtonStyle.SUCCESS)],
        [theme.button('Decline', icon='cross', callback_data=f'{PREFIX}:decline:{invitation}', style=ButtonStyle.DANGER)],
    ])


def build(ctx):
    async def press(client, query, rest):
        user = getattr(query, "from_user", None)
        chat = getattr(getattr(query, "message", None), "chat", None)
        if (
            type(getattr(user, "id", None)) is not int
            or user.id <= 0
            or getattr(chat, "id", None) != user.id
            or getattr(chat, "type", None) != ChatType.PRIVATE
        ):
            await query.answer(
                "Use the invitation in your private chat with this bot.",
                show_alert=True,
            )
            return
        try:
            parts = rest.split(":")
            if len(parts) != 2 or parts[0] not in ("accept", "decline"):
                raise FederationError("Invalid federation invitation.")
            state = await change(ctx, parts[0], user.id, invitation=parts[1])
            await query.answer(
                "Accepted." if parts[0] == "accept" else "Declined.", show_alert=True
            )
            try:
                await query.edit_message_text(
                    "Federation invitation "
                    + ("accepted" if parts[0] == "accept" else "declined")
                    + ". "
                    + (
                        "You are now the federation owner; the previous owner retains no automatic role."
                        if parts[0] == "accept" and state["kind"] == "owner"
                        else ""
                    ),
                    reply_markup=None,
                )
            except Exception:
                pass  # committed state is authoritative even if the old invitation cannot be edited
        except FederationError as error:
            await query.answer(str(error), show_alert=True)

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(PREFIX + ":x"):
        router.register(PREFIX, press)

    def handler(command):
        async def call(client, message):
            actor = getattr(getattr(message, "from_user", None), "id", None)
            if (
                type(actor) is not int
                or actor <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use your personal Telegram identity for federation roles."
                )
                return
            try:
                args = (getattr(message, "text", "") or "").split()[1:]
                if command == "feddemoteme":
                    if len(args) != 1:
                        raise FederationError("Usage: /feddemoteme federation-ID")
                    await change(ctx, "resign", actor, federation=args[0])
                    await reply(
                        message,
                        "You are no longer an administrator in that federation.",
                    )
                    return
                target = await resolve(client, message)
                uid = getattr(target, "id", None)
                if getattr(target, "is_bot", False):
                    raise FederationError(
                        "Federation roles require a personal user, not a bot."
                    )
                if command == "feddemote":
                    await change(ctx, "demote", actor, target=uid)
                    await reply(
                        message,
                        "Federation administrator access and pending invitations removed for that user.",
                    )
                    return
                if router is None:
                    raise FederationError(
                        "Private federation confirmations are unavailable; no invitation created."
                    )
                kind = "owner" if command == "fedtransfer" else "admin"
                state = await change(ctx, "invite", actor, target=uid, kind=kind)
                warning = (
                    "Accepting transfers ownership to you. The current owner loses their automatic role."
                    if kind == "owner"
                    else "Accepting makes you a federation administrator. This does not grant Telegram chat administrator rights."
                )
                try:
                    sent = await send(
                        client, uid,
                        f"<b>Federation {'ownership' if kind == 'owner' else 'administrator'} invitation</b>\n"
                        f"Federation: {html.escape(state['name'])}\nID: <code>{state['id']}</code>\nInvited by: <code>{actor}</code>\n"
                        f"{warning}\nExpires in 10 minutes. No permissions change until you accept.",
                        reply_markup=invitation_keyboard(ctx.theme, state['invitation']),
                    )
                    if sent is None:
                        raise RuntimeError("unconfirmed send")
                except Exception:
                    await reply(
                        message,
                        "Invitation recorded, but private delivery was not confirmed. No permissions changed. Ask the recipient to start this bot privately, then issue the command again; the new invitation replaces the old one.",
                    )
                    return
                await reply(
                    message,
                    "Private invitation sent. No permissions change until the recipient accepts within 10 minutes.",
                )
            except (FederationError, ValueError) as error:
                await reply(message, html.escape(str(error)))
            except Exception:
                await reply(
                    message,
                    "Federation role operation could not be confirmed. Refresh before retrying.",
                )

        return call

    return {command: handler(command) for command in COMMANDS}
