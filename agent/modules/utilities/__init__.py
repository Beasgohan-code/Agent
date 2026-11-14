"""Utilities module — ``id``, ``info`` and ``time``."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...ui.keyboards import SOURCE_URL
from ...ui.tables import kv_table, panel
from ..moderation import is_moderator
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
    async def no_args(message, command):
        if len((getattr(message, 'text', '') or '').split()) > 1:
            await reply(message, f'Usage: <code>/{command}</code> without arguments; reply to a message to select a user where supported.')
            return False
        return True

    async def show_id(_client, message):
        if not await no_args(message, 'id'):
            return
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
        sender_chat = getattr(message, 'sender_chat', None)
        if sender_chat is not None:
            lines.append(f"Sender chat: <code>{sender_chat.id}</code>")
        replied = getattr(message, 'reply_to_message', None)
        replied_sender = getattr(replied, 'sender_chat', None)
        if replied_sender is not None:
            lines.append(f"Replied sender chat: <code>{replied_sender.id}</code>")
        await reply(message, panel('Identifiers', icon=ctx.theme.emoji('info'), lines=lines,
            note='Identifiers are visible in this chat. A sender-chat identity is not proof of the human administrator behind it.',
            footer='/info · /time · /help'))

    async def show_info(client, message):
        if not await no_args(message, 'info'):
            return
        replied = getattr(message, 'reply_to_message', None)
        if replied is not None and getattr(replied, 'from_user', None) is None:
            await reply(message, panel('User identity unavailable', icon=ctx.theme.emoji('lock'),
                lines=['The replied message has no visible user identity. Use /id for sender-chat identifiers; the hidden human cannot be inferred.']))
            return
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
        manager = await is_moderator(client, message, owner_id=ctx.settings.owner_id)
        if ctx.chats is not None and manager:
            warnings = ctx.chats.active_warning_count(message.chat.id, target.id)
            if warnings:
                lines.append(f"Warnings: {warnings}")
            if ctx.chats.is_trusted(message.chat.id, target.id):
                lines.append("Trusted: yes")
        if member is None:
            lines.append('Status here: unavailable (lookup not confirmed)')
        await reply(message, panel('Member profile', icon=ctx.theme.emoji('user'),
            lines=lines[1:], note='Public Telegram identity only. Moderation details are added only for authorized moderators; replies are still visible to this chat.',
            footer='/id · /help info'))

    async def show_time(_client, message):
        args = (getattr(message, 'text', '') or '').split()[1:]
        if len(args) > 1 or (args and len(args[0]) > 100):
            await reply(message, 'Usage: <code>/time [Area/City]</code>, for example <code>/time Asia/Kolkata</code>.')
            return
        name = args[0] if args else 'UTC'
        try:
            zone = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            await reply(message, 'Unknown timezone. Use an IANA name such as <code>Asia/Kolkata</code>, <code>Europe/London</code> or <code>UTC</code>.')
            return
        now = datetime.now(timezone.utc)
        local = now.astimezone(zone)
        await reply(message, panel('World clock', icon=ctx.theme.emoji('globe'),
            table=kv_table([('Timezone', name), ('Date', local.strftime('%Y-%m-%d')),
                            ('Time', local.strftime('%H:%M:%S')), ('UTC offset', local.strftime('%z')),
                            ('UTC', now.strftime('%Y-%m-%d %H:%M:%S'))]),
            note='Current timezone rules apply, including daylight-saving changes. No timezone preference is stored.',
            footer='/time Asia/Kolkata · /time UTC'))

    async def repo(_client, message):
        """Where the source lives — one button, no wall of links."""
        if not await no_args(message, 'repo'):
            return
        await reply(
            message,
            panel(
                "Source",
                icon=ctx.theme.emoji("link"),
                table=kv_table(
                    [
                        ("Code", SOURCE_URL),
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
