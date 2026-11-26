"""Verification sessions and their bound buttons.

Pending records are currently process-local. A missing session never authorizes
lifting a restriction. Callbacks and timeouts serialize per member, recheck
membership, and use the current group defaults rather than generic open rights.
"""

from __future__ import annotations

import asyncio
import logging
import html
import re
from weakref import WeakValueDictionary

from pyrogram.enums import ButtonStyle, ChatMemberStatus, ChatType
from pyrogram.types import ChatPermissions
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...ui.tables import kv_table, panel
from ...ui.theme import Theme
from ...utils.rich import reply, send
from ..moderation import is_moderator, kick_member, PartialKickError

logger = logging.getLogger(__name__)

PREFIX = "verify"


DEFAULT_TIMEOUT_MINUTES = 10


MAX_TIMEOUT_MINUTES = 120


SILENCED = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)


def enabled(chats, chat_id: int) -> bool:
    return bool(chats.get(chat_id, "verify_enabled", False))


def timeout_minutes(chats, chat_id: int) -> int:
    raw = chats.get(chat_id, "verify_timeout", DEFAULT_TIMEOUT_MINUTES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_MINUTES
    return max(1, min(MAX_TIMEOUT_MINUTES, value))


def button_for(chat_id: int, user_id: int, *, theme=None) -> Keyboard:
    theme = theme or Theme()
    return Keyboard(
        [
            [
                theme.button(
                    "I am human", icon="check",
                    callback_data=f"{PREFIX}:{int(chat_id)}:{int(user_id)}",
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
    )


def parse_press(rest: str) -> tuple[int, int] | None:
    """``<chat>:<user>`` from callback data, or ``None`` when malformed."""
    if not re.fullmatch(r"-[0-9]{1,19}:[0-9]{1,19}", rest or ""):
        return None
    parts = rest.split(":")
    chat_id, user_id = int(parts[0]), int(parts[1])
    if chat_id >= 0 or user_id <= 0 or abs(chat_id) >= 2**63 or user_id >= 2**63:
        return None
    return chat_id, user_id


class Verifier:
    """Owns the pending set, the timer tasks and the button handler."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._chats = ctx.chats
        #: (chat_id, user_id) → the task that would remove them.
        self.pending: dict[tuple[int, int], asyncio.Task] = {}
        #: (chat_id, user_id) → (chat_id, prompt message id)
        self.prompts: dict[tuple[int, int], tuple[int, int]] = {}
        self._locks = WeakValueDictionary()

    # -- button ------------------------------------------------------------

    async def on_press(self, client, query, rest: str) -> None:
        parsed = parse_press(rest)
        if parsed is None:
            await query.answer("This button is malformed.", show_alert=True)
            return
        chat_id, user_id = parsed
        presser = getattr(getattr(query, "from_user", None), "id", None)
        if presser != user_id:
            await query.answer("This button belongs to someone else.", show_alert=True)
            return
        origin = getattr(query, "message", None)
        if getattr(getattr(origin, "chat", None), "id", None) != chat_id:
            await query.answer("This verification button belongs to a different group.", show_alert=True)
            return
        key = (chat_id, user_id)
        async with self._locks.setdefault(key, asyncio.Lock()):
            task = self.pending.get(key)
            location = self.prompts.get(key)
            if task is None or location is None:
                await query.answer("This verification session is no longer active.", show_alert=True)
                return
            if location != (chat_id, getattr(origin, "id", None)):
                await query.answer("This verification prompt is no longer valid.", show_alert=True)
                return
            try:
                member = await client.get_chat_member(chat_id, user_id)
                status = getattr(member, "status", None)
                if status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
                    await query.answer("Membership changed. Ask a group administrator for help.", show_alert=True)
                    return
                chat = await client.get_chat(chat_id)
                permissions = getattr(chat, "permissions", None)
                if permissions is None:
                    await query.answer("Cannot read group permissions. Please try again.", show_alert=True)
                    return
                await client.restrict_chat_member(chat_id, user_id, permissions)
            except Exception:
                # Retain the session and timeout when Telegram does not confirm.
                await query.answer("I could not confirm verification. Please try again.", show_alert=True)
                return
            self.pending.pop(key, None)
            self.prompts.pop(key, None)
            if not task.done():
                task.cancel()
            self._chats.log(chat_id, "verify", actor_id=user_id, target_id=user_id)
            await query.answer("Verified — welcome!")
            try:
                await client.edit_message_text(chat_id, location[1], "Verified. Welcome to the group.")
            except Exception as error:
                logger.warning("#Errors Verification prompt edit unconfirmed (%s)", type(error).__name__)

    # -- timer -------------------------------------------------------------

    async def _remove_later(self, client, chat_id: int, user_id: int, minutes: int) -> None:
        try:
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            raise
        key = (chat_id, user_id)
        async with self._locks.setdefault(key, asyncio.Lock()):
            # An old timer must never expire a replacement session for this user.
            if self.pending.get(key) is not asyncio.current_task():
                return
            self.pending.pop(key, None)
            self.prompts.pop(key, None)
            try:
                member = await client.get_chat_member(chat_id, user_id)
                status = getattr(member, "status", None)
                if status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                    return
                if status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
                    self._chats.log(chat_id, "verify:timeout_not_attempted", actor_id=None,
                                    target_id=user_id, reason="protected or unknown membership")
                    return
                await kick_member(client, self._ctx, chat_id, user_id, source="verification")
                self._chats.log(chat_id, "verify:timeout", actor_id=None, target_id=user_id)
            except PartialKickError:
                logger.warning("Verification timeout kick incomplete; see group audit.")
            except Exception as exc:
                self._chats.log(chat_id, "verify:timeout_failed", actor_id=None,
                                target_id=user_id, reason=type(exc).__name__)
                logger.warning("Could not remove unverified member: %s", type(exc).__name__)

    async def shutdown(self):
        """Do not leave verification timers running after bot shutdown."""
        tasks = list(self.pending.values())
        self.pending.clear()
        self.prompts.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- /verify -----------------------------------------------------------

    async def verify(self, client, message) -> None:
        chat = getattr(message, "chat", None)
        if chat is None or getattr(chat, "type", None) not in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        ):
            await reply(message, "Verification is a group setting.")
            return
        if not await is_moderator(
            client, message, need="can_restrict_members",
            owner_id=self._ctx.settings.owner_id,
        ):
            await reply(message, "You need the restrict-members right to change this.")
            return

        parts = (getattr(message, "text", "") or "").split()
        args = [part.lower() for part in parts[1:]]
        if args:
            changed = True
            if args[0] in ("on", "off"):
                self._chats.put(chat.id, "verify_enabled", args[0] == "on")
            elif args[0] == "timeout" and len(args) > 1 and args[1].isdigit():
                self._chats.put(
                    chat.id,
                    "verify_timeout",
                    max(1, min(MAX_TIMEOUT_MINUTES, int(args[1]))),
                )
            else:
                changed = False
                await reply(message, 
                    "Usage: <code>/verify on|off</code> or "
                    "<code>/verify timeout 10</code> (minutes, 1–120)."
                )
            if not changed:
                return
            self._chats.log(
                chat.id, "verify:config", actor_id=message.from_user.id,
                reason=" ".join(args),
            )

        waiting = sum(1 for key in self.pending if key[0] == chat.id)
        await reply(message, 
            panel(
                "Member verification",
                icon=self._ctx.theme.emoji("lock"),
                table=kv_table(
                    [
                        ("Enabled", "yes" if enabled(self._chats, chat.id) else "no"),
                        ("Timeout", f"{timeout_minutes(self._chats, chat.id)} min"),
                        ("Waiting now", str(waiting)),
                    ]
                ),
                note=(
                    "New members are muted until they press the button. Change it with "
                    "<code>/verify on|off</code> or <code>/verify timeout 10</code>."
                ),
                footer="Pending verifications live in this process, not on disk.",
            )
        )

    # -- join watcher ------------------------------------------------------

    async def on_member_update(self, client, update) -> None:
        chat_id = getattr(getattr(update, "chat", None), "id", None)
        user_id = getattr(getattr(getattr(update, "new_chat_member", None), "user", None), "id", None)
        if type(chat_id) is not int or chat_id >= 0 or type(user_id) is not int or user_id <= 0:
            return
        async with self._locks.setdefault((chat_id, user_id), asyncio.Lock()):
            await self._on_member_update(client, update)

    async def _on_member_update(self, client, update) -> None:
        try:
            chat = getattr(update, "chat", None)
            if chat is None or getattr(chat, "type", None) not in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                return
            if not enabled(self._chats, chat.id):
                return
            new = getattr(update, "new_chat_member", None)
            old = getattr(update, "old_chat_member", None)
            if new is None or old is None:
                return
            joined = (
                getattr(new, "status", None) == ChatMemberStatus.MEMBER
                and getattr(old, "status", None) in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            )
            if not joined:
                return
            user = getattr(new, "user", None)
            if user is None or getattr(user, "is_bot", False):
                return
            key = (int(chat.id), int(user.id))
            if key in self.pending or self._chats.is_trusted(chat.id, user.id):
                return
            current = await client.get_chat_member(chat.id, user.id)
            if getattr(current, "status", None) not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
                return
            baseline = getattr(await client.get_chat(chat.id), "permissions", None)
            if baseline is None:
                return
            await client.restrict_chat_member(chat.id, user.id, SILENCED)
            minutes = timeout_minutes(self._chats, chat.id)
            try:
                prompt = await send(
                    client, chat.id,
                    f"{html.escape(getattr(user, 'first_name', None) or 'Welcome')}, please confirm you are human "
                    f"within {minutes} minutes.",
                    reply_markup=button_for(chat.id, user.id, theme=self._ctx.theme),
                )
            except Exception as exc:
                try:
                    await client.restrict_chat_member(chat.id, user.id, baseline)
                    action = "verify:prompt_failed"
                except Exception:
                    action = "verify:recovery_required"
                self._chats.log(chat.id, action, actor_id=None, target_id=user.id,
                                reason=type(exc).__name__)
                return
            key = (int(chat.id), int(user.id))
            self.prompts[key] = (int(chat.id), getattr(prompt, "id", 0))
            self.pending[key] = asyncio.create_task(
                self._remove_later(client, int(chat.id), int(user.id), minutes),
                name=f"verify-{chat.id}-{user.id}",
            )
            self._chats.log(chat.id, "verify:prompt", actor_id=None, target_id=int(user.id))
            logger.info(
                "verification prompt chat=%s user=%s timeout_minutes=%s",
                chat.id,
                user.id,
                minutes,
            )
        except Exception as error:  # noqa: BLE001 - a watcher must never break the client
            logger.error("#Errors Verification watcher failed (%s)", type(error).__name__)
