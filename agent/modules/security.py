"""Security — member verification, from Meikoagent's ``security`` plugin.

A new member is muted on arrival and asked to press one button. When they press
it, the mute is lifted. If they never press it, they are removed after the
configured timeout. That is the whole feature, and every part of it is real:
a restriction Telegram applies, a button Telegram delivers, a timer this process
holds, and a removal Telegram performs.

Deliberate limits, stated rather than implied:

* the pending set lives in memory — a restart forgets who was mid-verification
  (their mute stays, because Telegram keeps it; an administrator can lift it);
* verification is **off** by default and switches on with ``/verify on``;
* ``/lockdown`` already exists in the group module and is not duplicated here.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import ChatMemberUpdatedHandler
from pyrogram.types import ChatPermissions
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ..platform.actions import ActionRouter
from ..platform.manifest import PluginManifest
from ..ui.tables import kv_table, panel
from .moderation import is_moderator
from ..utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="security",
    name="Security & verification",
    version="1.0.0",
    description="Mute new members until they press a button; remove them if they never do.",
    commands=("verify",),
    permissions=("messages.send", "chats.restrict", "chats.ban"),
    scope="group",
)

PREFIX = "verify"
DEFAULT_TIMEOUT_MINUTES = 10
MAX_TIMEOUT_MINUTES = 120

SILENCED = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)
RESTORED = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
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


def button_for(chat_id: int, user_id: int) -> Keyboard:
    return Keyboard(
        [[Button("I am human", callback_data=f"{PREFIX}:{int(chat_id)}:{int(user_id)}")]]
    )


def parse_press(rest: str) -> tuple[int, int] | None:
    """``<chat>:<user>`` from callback data, or ``None`` when malformed."""
    parts = (rest or "").split(":")
    if len(parts) != 2 or not all(part.lstrip("-").isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


class Verifier:
    """Owns the pending set, the timer tasks and the button handler."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._chats = ctx.chats
        #: (chat_id, user_id) → the task that would remove them.
        self.pending: dict[tuple[int, int], asyncio.Task] = {}
        #: (chat_id, user_id) → (chat_id, prompt message id)
        self.prompts: dict[tuple[int, int], tuple[int, int]] = {}

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
        task = self.pending.pop((chat_id, user_id), None)
        if task is None:
            await query.answer("You are already verified.", show_alert=False)
        try:
            await client.restrict_chat_member(chat_id, user_id, RESTORED)
        except Exception:  # noqa: BLE001 - the member is told
            await query.answer("I could not lift your restriction.", show_alert=True)
            return
        if task is not None and not task.done():
            task.cancel()
        self._chats.log(chat_id, "verify", actor_id=user_id, target_id=user_id)
        await query.answer("Verified — welcome!")
        location = self.prompts.pop((chat_id, user_id), None)
        if location is not None:
            chat, message_id = location
            try:
                await client.edit_message_text(
                    chat, message_id, "Verified. Welcome to the group."
                )
            except Exception:  # noqa: BLE001 - cosmetics only
                logger.debug("could not edit the verification prompt", exc_info=True)

    # -- timer -------------------------------------------------------------

    async def _remove_later(self, client, chat_id: int, user_id: int, minutes: int) -> None:
        try:
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            raise
        if (chat_id, user_id) not in self.pending:
            return
        self.pending.pop((chat_id, user_id), None)
        self.prompts.pop((chat_id, user_id), None)
        try:
            await client.ban_chat_member(chat_id, user_id)
            await client.unban_chat_member(chat_id, user_id)
            logger.info("verification timed out for %s in %s", user_id, chat_id)
        except Exception:  # noqa: BLE001 - logged; nothing else to do
            logger.exception("could not remove unverified member")

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
            await client.restrict_chat_member(chat.id, user.id, SILENCED)
            minutes = timeout_minutes(self._chats, chat.id)
            prompt = await client.send_message(
                chat.id,
                f"{getattr(user, 'first_name', 'Welcome')}, please confirm you are human "
                f"within {minutes} minutes.",
                reply_markup=button_for(chat.id, user.id),
            )
            key = (int(chat.id), int(user.id))
            self.prompts[key] = (int(chat.id), getattr(prompt, "id", 0))
            self.pending[key] = asyncio.create_task(
                self._remove_later(client, int(chat.id), int(user.id), minutes),
                name=f"verify-{chat.id}-{user.id}",
            )
            self._chats.log(chat.id, "verify:prompt", actor_id=None, target_id=int(user.id))
        except Exception:  # noqa: BLE001 - a watcher must never break the client
            logger.exception("verification watcher failed")


def verifier(ctx) -> Verifier:
    """The one Verifier for this context (built once by :func:`build`)."""
    existing = getattr(ctx, "verifier", None)
    if existing is None:
        existing = Verifier(ctx)
        ctx.verifier = existing
        router = getattr(ctx, "actions", None)
        if isinstance(router, ActionRouter):
            router.register(PREFIX, existing.on_press)
    return existing


def build(ctx):
    """Wire ``/verify`` and share one :class:`Verifier` with the watcher."""
    instance = verifier(ctx)
    return MANIFEST, {"verify": instance.verify}


def extra_handlers(ctx):
    """The join watcher that mutes unverified members."""
    instance = verifier(ctx)
    return [ChatMemberUpdatedHandler(instance.on_member_update)]
