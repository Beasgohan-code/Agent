"""Welcome module — greetings for joins and farewells for leaves.

The command names come from ``CBML``/``WZML-X`` and ``Meikoagent``'s welcome
plugin (``setwelcome``, ``welcome``, ``goodbye``). The behaviour here is driven
by real ``ChatMemberUpdated`` events, so a greeting only ever fires when
Telegram actually reports a join or a leave.
"""

from __future__ import annotations

import html
import logging

from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import ChatMemberUpdatedHandler

from ..platform.manifest import PluginManifest

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="welcome",
    name="Welcome",
    version="1.0.0",
    description="Welcome and goodbye messages driven by real membership changes.",
    commands=("setwelcome", "welcome", "goodbye"),
    permissions=("messages.read", "messages.send"),
    scope="group",
)

KINDS = ("welcome", "goodbye")
DEFAULT_WELCOME = "Welcome {mention} to {chat}!"


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def render(template: str, *, user, chat, count: int | None) -> str:
    """Fill the small, documented placeholder set — nothing dynamic is invented.

    The stored template is escaped first. Replies are sent with HTML parsing on,
    so an unescaped ``<`` in a greeting would either inject markup into the group
    or make Telegram reject the message outright. The only markup that reaches
    the chat is the mention link built below.
    """
    name = getattr(user, "first_name", None) or "there"
    mention = (
        f'<a href="tg://user?id={int(user.id)}">{html.escape(name)}</a>'
        if getattr(user, "id", None)
        else html.escape(name)
    )
    title = getattr(chat, "title", None) or "the group"
    return (
        html.escape(template or "").replace("{mention}", mention)
        .replace("{name}", html.escape(name))
        .replace("{chat}", html.escape(str(title)))
        .replace("{count}", str(count) if count is not None else "?")
    )


async def _count(client, chat_id: int) -> int | None:
    try:
        return await client.get_chat_members_count(chat_id)
    except Exception:  # noqa: BLE001 - the count is a nicety, not a requirement
        return None


def watch(ctx):
    """React to real join/leave events."""

    async def on_update(client, update):
        try:
            chat = getattr(update, "chat", None)
            if chat is None or getattr(chat, "type", None) not in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                return
            new = getattr(update, "new_chat_member", None)
            old = getattr(update, "old_chat_member", None)
            if new is None or old is None:
                return
            user = getattr(new, "user", None) or getattr(update, "from_user", None)
            if user is None:
                return

            joined = (
                getattr(new, "status", None) == ChatMemberStatus.MEMBER
                and getattr(old, "status", None) in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            )
            left = (
                getattr(new, "status", None) in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
                and getattr(old, "status", None) == ChatMemberStatus.MEMBER
            )
            kind = "welcome" if joined else "goodbye" if left else None
            if kind is None:
                return

            greeting = ctx.chats.greeting(chat.id, kind)
            if not greeting["enabled"] or not greeting["text"]:
                return
            count = await _count(client, chat.id) if "{count}" in greeting["text"] else None
            await client.send_message(
                chat.id, render(greeting["text"], user=user, chat=chat, count=count)
            )
        except Exception:  # noqa: BLE001 - watchers must never break the client
            logger.exception("welcome watcher failed")

    return on_update


def extra_handlers(ctx):
    return [ChatMemberUpdatedHandler(watch(ctx))]


def build(ctx):
    async def _guard(client, message) -> bool:
        from .moderation import is_moderator

        if await is_moderator(client, message, need="can_change_info", owner_id=ctx.settings.owner_id):
            return True
        await message.reply("Only chat administrators can change greetings.")
        return False

    async def setwelcome(client, message):
        if not await _guard(client, message):
            return
        text = " ".join(_args(message)[1:]).strip()
        if not text:
            await message.reply(
                "Usage: <code>/setwelcome Welcome {mention} to {chat}!</code>\n"
                "Placeholders: {mention} {name} {chat} {count}. The text is sent "
                "as plain text, so markup in it is shown, not applied."
            )
            return
        ctx.chats.set_greeting(message.chat.id, "welcome", text)
        await message.reply("Welcome message saved and enabled.")

    async def welcome(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        if len(args) > 1 and args[1].lower() in ("on", "off"):
            state = ctx.chats.toggle_greeting(
                message.chat.id, "welcome", args[1].lower() == "on"
            )
            await message.reply(
                f"Welcome messages are now {'on' if state['enabled'] else 'off'}."
            )
            return
        current = ctx.chats.greeting(message.chat.id, "welcome")
        await message.reply(
            "<b>Welcome message</b>\n"
            f"Status: {'on' if current['enabled'] else 'off'}\n"
            f"Text: {html.escape(current['text']) or '<i>not set</i>'}\n\n"
            "Change it with <code>/setwelcome text</code>, toggle with "
            "<code>/welcome on|off</code>."
        )

    async def goodbye(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        if len(args) > 1 and args[1].lower() in ("on", "off"):
            state = ctx.chats.toggle_greeting(
                message.chat.id, "goodbye", args[1].lower() == "on"
            )
            await message.reply(
                f"Goodbye messages are now {'on' if state['enabled'] else 'off'}."
            )
            return
        text = " ".join(args[1:]).strip()
        if not text:
            current = ctx.chats.greeting(message.chat.id, "goodbye")
            await message.reply(
                "<b>Goodbye message</b>\n"
                f"Status: {'on' if current['enabled'] else 'off'}\n"
                f"Text: {html.escape(current['text']) or '<i>not set</i>'}\n\n"
                "Set one with <code>/goodbye text</code>."
            )
            return
        ctx.chats.set_greeting(message.chat.id, "goodbye", text)
        await message.reply("Goodbye message saved and enabled.")

    return MANIFEST, {"setwelcome": setwelcome, "welcome": welcome, "goodbye": goodbye}
