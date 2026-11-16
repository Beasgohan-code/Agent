"""Utilities module — ``id``, ``info`` and ``time``."""

from __future__ import annotations

import html
import logging
import asyncio
import re
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.types import InlineKeyboardMarkup
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from ...platform.manifest import PluginManifest
from ...ui.keyboards import nav_keyboard
from ...ui.tables import kv_table, panel
from ..moderation import is_moderator
from ...utils.rich import reply, edit

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=False,
    slug="utilities",
    name="Utilities",
    version="1.0.0",
    description="Chat/member identifiers, member details and the current time.",
    commands=("id", "info", "myinfo", "userinfo", "time", "repo", "gu", "tiktok", "x", "yt", "ig"),
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

    async def render_profile(client, message, *, target=None):
        replied = getattr(message, 'reply_to_message', None)
        if target is None and replied is not None and getattr(replied, 'from_user', None) is None:
            await reply(message, panel('User identity unavailable', icon=ctx.theme.emoji('lock'),
                lines=['The replied message has no visible user identity. Use /id for sender-chat identifiers; the hidden human cannot be inferred.']))
            return
        target = target or _replied(message) or getattr(message, "from_user", None)
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
        if ctx.chats is not None and manager and message.chat.id < 0:
            warnings = await ctx.chats.aactive_warning_count(message.chat.id, target.id)
            if warnings:
                lines.append(f"Warnings: {warnings}")
            from ...platform.group_trust import trusted_members, TrustError
            try:
                if target.id in await trusted_members(ctx, message.chat.id):
                    lines.append("Approved: yes")
            except TrustError:
                lines.append("Approval: unavailable")
        if member is None:
            lines.append('Status here: unavailable (lookup not confirmed)')
        await reply(message, panel('Member profile', icon=ctx.theme.emoji('user'),
            lines=lines[1:], note='Public Telegram identity only. Moderation details are added only for authorized moderators; replies are still visible to this chat.',
            footer='/id · /help info'))

    async def show_info(client, message):
        parts = (getattr(message, 'text', '') or '').split()
        if len(parts) > 2:
            await reply(message, 'Usage: <code>/info [@username|positive ID]</code>, or reply to a member.')
            return
        target = None
        if len(parts) == 2:
            value = parts[1]
            if re.fullmatch(r'[1-9][0-9]{0,18}', value) and int(value) < 2**63:
                value = int(value)
            elif not re.fullmatch(r'@[A-Za-z0-9_]{1,32}', value):
                await reply(message, 'Usage: <code>/info [@username|positive ID]</code>, or reply to a member.')
                return
            try:
                target = await asyncio.wait_for(client.get_users(value), timeout=5)
                if type(getattr(target, 'id', None)) is not int or target.id <= 0:
                    raise RuntimeError('No personal user identity')
            except Exception as error:
                logging.getLogger(__name__).warning('#Errors User lookup unavailable (%s)', type(error).__name__)
                await reply(message, 'User lookup unavailable. Check the username or ID; no private profile details were inferred.')
                return
        await render_profile(client, message, target=target)

    async def myinfo(client, message):
        if not await no_args(message, 'myinfo'):
            return
        target = getattr(message, 'from_user', None)
        if target is None or getattr(message, 'sender_chat', None) is not None:
            await reply(message, 'Your personal user identity is unavailable. Use /id for sender-chat details.')
            return
        await render_profile(client, message, target=target)

    async def userinfo(client, message):
        if len((getattr(message, 'text', '') or '').split()) == 1 and _replied(message) is None:
            await reply(message, 'Usage: <code>/userinfo @username</code> or positive ID, or reply to a member.')
            return
        await show_info(client, message)

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

    async def gu(client, message):
        parts = (getattr(message, 'text', '') or '').split()
        user = getattr(message, 'from_user', None)
        chat = getattr(message, 'chat', None)
        if user is None or getattr(message, 'sender_chat', None) is not None:
            await reply(message, 'Use your personal Telegram identity for this demo.')
            return
        if len(parts) > 2 or (len(parts) == 2 and parts[1].lower() != 'fail'):
            await reply(message, 'Usage: <code>/gu [fail]</code> — visual demo only; no AI request is sent.')
            return
        if getattr(chat, 'type', None) in (ChatType.GROUP, ChatType.SUPERGROUP):
            if not await is_moderator(client, message):
                await reply(message, 'Only current group admins can run this card demo here.')
                return
        elif getattr(chat, 'type', None) != ChatType.PRIVATE or chat.id != user.id:
            await reply(message, 'Run this demo in private chat or a group where you are an admin.')
            return
        failed = len(parts) == 2
        sent = await reply(message, panel('Live card demo', icon=ctx.theme.emoji('sparkles'),
            lines=['Preparing this demonstration card…'],
            note='Visual demonstration only. No AI request, hidden reasoning or background job.'),
            reply_markup=nav_keyboard())
        if sent is None:
            return  # No confirmed message to edit; never manufacture completion.
        keys = InlineKeyboardMarkup([[ctx.theme.button('Help', icon='help', callback_data='menu:help', style=ButtonStyle.PRIMARY),
                                     ctx.theme.button('Main menu', icon='bot', callback_data='menu:home')]])
        try:
            await edit(sent, panel('Simulated failure' if failed else 'Demo completed',
                icon=ctx.theme.emoji('warn' if failed else 'check'),
                lines=['This is an intentional failure-state preview. Nothing failed outside this demo.' if failed
                       else 'This same message has been updated from preparing to completed.'],
                note='Demo only. No AI/provider request or background task was performed. Run /gu or /gu fail to preview again.'),
                reply_markup=keys)
        except Exception as error:
            logging.getLogger(__name__).warning('#Errors Card demo edit unconfirmed (%s)', type(error).__name__)
            await reply(message, 'Demo update unconfirmed. No automatic retry; no background task was started.')

    async def repo(_client, message):
        """Keep the legacy command reachable without publishing source links."""
        if not await no_args(message, 'repo'):
            return
        await reply(
            message,
            panel(
                "Bot information",
                icon=ctx.theme.emoji("info"),
                table=kv_table([("Running", f"v{_version()}")]),
                note="Source links are not published in this bot. Use /help for available commands.",
            ),
            reply_markup=nav_keyboard(),
        )

    from .social import build as social_cards
    return MANIFEST, {**social_cards(ctx), "id": show_id, "info": show_info, "myinfo": myinfo, "userinfo": userinfo, "time": show_time, "repo": repo, "gu": gu}
