"""Utilities module — ``id``, ``info`` and ``time``."""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...ui.keyboards import SOURCE_URL
from ...ui.tables import kv_table, panel
from ...utils.rich import reply

MANIFEST = PluginManifest(
    slug="utilities",
    name="Utilities",
    version="1.0.0",
    description="Chat/member identifiers, member details and the current time.",
    commands=("id", "info", "time", "repo"),
    permissions=("messages.read",),
    scope="all",
)


def _version() -> str:
    from ... import __version__

    return __version__


def _replied(message):
    replied = getattr(message, "reply_to_message", None)
    return getattr(replied, "from_user", None) if replied is not None else None


def build(ctx):
    async def show_id(_client, message):
        user = getattr(message, "from_user", None)
        lines = [f"Chat id: <code>{message.chat.id}</code>"]
        if user is not None:
            lines.append(f"Your id: <code>{user.id}</code>")
        target = _replied(message)
        if target is not None:
            lines.append(f"Replied user: <code>{target.id}</code>")
        message_id = getattr(message, "id", None) or getattr(message, "message_id", None)
        if message_id is not None:
            lines.append(f"Message id: <code>{message_id}</code>")
        thread_id = getattr(message, "message_thread_id", None)
        if thread_id:
            lines.append(f"Topic id: <code>{thread_id}</code>")
        await reply(message, "\n".join(lines))

    async def show_info(client, message):
        target = _replied(message) or getattr(message, "from_user", None)
        if target is None:
            await reply(message, "Reply to a member, or run this in a chat where I can see you.")
            return
        name = " ".join(
            part
            for part in (
                getattr(target, "first_name", None),
                getattr(target, "last_name", None),
            )
            if part
        ) or "unknown"
        lines = [
            "<b>Member info</b>",
            f"Name: {html.escape(name)}",
            f"Id: <code>{target.id}</code>",
        ]
        username = getattr(target, "username", None)
        if username:
            lines.append(f"Username: @{html.escape(username)}")
        if getattr(target, "is_bot", False):
            lines.append("Bot: yes")
        member = None
        try:
            member = await client.get_chat_member(message.chat.id, target.id)
        except Exception:  # noqa: BLE001 - not a member, or no rights to ask
            member = None
        if member is not None:
            status = getattr(member, "status", None)
            lines.append(f"Status here: {getattr(status, 'name', 'unknown').title()}")
        if ctx.chats is not None:
            warnings = ctx.chats.active_warning_count(message.chat.id, target.id)
            if warnings:
                lines.append(f"Warnings: {warnings}")
            if ctx.chats.is_trusted(message.chat.id, target.id):
                lines.append("Trusted: yes")
        await reply(message, "\n".join(lines))

    async def show_time(_client, message):
        now = datetime.now(timezone.utc)
        local = time.localtime()
        await reply(message, 
            "<b>Time</b>\n"
            f"UTC: <code>{now:%Y-%m-%d %H:%M:%S}</code>\n"
            f"Server: <code>{time.strftime('%Y-%m-%d %H:%M:%S', local)}</code> ({time.tzname[0]})"
        )

    async def repo(_client, message):
        """Where the source lives — one button, no wall of links."""
        await reply(
            message,
            panel(
                "Source",
                icon=ctx.theme.emoji("link"),
                table=kv_table(
                    [
                        ("Code", f"<code>{html.escape(SOURCE_URL)}</code>"),
                        ("Running", f"v{_version()}"),
                    ]
                ),
                footer="Issues and pull requests go to the repository above.",
            ),
            reply_markup=Keyboard(
                [
                    [
                        Button(
                            "\U0001f517 Open the repository",
                            url=SOURCE_URL,
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            ),
        )

    return MANIFEST, {"id": show_id, "info": show_info, "time": show_time, "repo": repo}
