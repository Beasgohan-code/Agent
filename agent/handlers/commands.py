"""Agent — command handlers."""

from __future__ import annotations

import logging

from ..ui.screens import help_lookup_screen, help_screen, ping_screen, welcome_screen
from ..ui.theme import Theme
from ..utils.sender import ScreenSender

logger = logging.getLogger(__name__)

FAILURE_NOTICE = "Something went wrong on my side. Please try again in a moment."


def start_payload(text: str) -> str:
    """The bit after ``/start`` in ``/start link_abc``; ``""`` when there is none.

    ``/start@thebot`` is the form Telegram puts in a group, and the payload may
    itself contain a space, so only the first token is treated as the command.
    """
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return ""
    command = parts[0].lstrip("/").split("@", 1)[0].lower()
    if command not in ("start", "restart_bot"):
        return ""
    return parts[1].strip() if len(parts) > 1 else ""


class CommandHandlers:
    """``/start``, ``/help`` and ``/ping``."""

    def __init__(self, sender: ScreenSender, theme: Theme, monitor=None, *,
                 events=None, users=None, start_image: str | None = None,
                 active_commands=None, deeplinks=None) -> None:
        self._sender = sender
        self._theme = theme
        self._monitor = monitor
        self._events = events
        self._users = users
        #: Picture above /start; a failure there falls back to the text screen.
        self._start_image = start_image
        #: Callable returning the commands that are actually registered.
        self._active_commands = active_commands
        #: ``/start <payload>`` router; ``None`` means this build has no deep links.
        self._deeplinks = deeplinks

    async def start(self, client, message) -> None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        payload = start_payload(getattr(message, "text", "") or "")
        if self._monitor is not None:
            self._monitor.record_activity("start")
        logger.info("/start%s from user %s", f" {payload}" if payload else "", user_id)
        if self._events is not None and user_id is not None:
            first = self._users.remember(user_id) if self._users is not None else False
            self._events.emit(
                "new_user" if first else "returning_user",
                uid=user_id,
                username=getattr(message.from_user, "username", None),
            )
        # A payload is a request, not a greeting: whoever owns that prefix answers
        # it instead of the welcome screen, which would silently swallow the link.
        if payload and self._deeplinks is not None and self._deeplinks.handles(payload):
            await self._deeplinks.dispatch(client, message, payload)
            return
        active = set(self._active_commands()) if self._active_commands is not None else None
        await self._greet(
            client, message, welcome_screen(message.from_user, self._theme, active=active)
        )

    async def _greet(self, client, message, screen) -> None:
        """``/start`` gets the picture; everything else gets plain text."""
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        try:
            await self._sender.send_hero(chat_id, screen, self._start_image)
        except Exception:
            logger.exception("Failed to deliver the welcome screen to chat %s", chat_id)
            await self._notify_failure(client, chat_id)

    async def help(self, client, message) -> None:
        """``/help`` opens the sections; ``/help <command|section>`` the one page."""
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if self._monitor is not None:
            self._monitor.record_activity("help")
        bits = (getattr(message, "text", None) or "").split(maxsplit=1)
        argument = bits[1].strip() if len(bits) > 1 else ""
        logger.info("/help %s from user %s", argument or "(overview)", user_id)
        active = set(self._active_commands()) if self._active_commands is not None else None
        screen = (
            help_lookup_screen(argument, message.from_user, self._theme, active=active)
            if argument
            else help_screen(message.from_user, self._theme, active=active)
        )
        await self._show(client, message, screen, "help")

    async def ping(self, client, message) -> None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if self._monitor is not None:
            self._monitor.record_activity("ping")
        logger.info("/ping from user %s", user_id)
        await self._show(client, message, ping_screen(self._monitor, self._theme), "ping")

    async def _show(self, client, message, screen, name: str) -> None:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        try:
            await self._sender.send(chat_id, screen)
        except Exception:
            logger.exception("Failed to deliver the %s screen to chat %s", name, chat_id)
            await self._notify_failure(client, chat_id)

    @staticmethod
    async def _notify_failure(client, chat_id) -> None:
        """Last-resort plain-text notice; never raises."""
        try:
            await client.send_message(chat_id=chat_id, text=FAILURE_NOTICE)
        except Exception:
            logger.exception("Could not even send the failure notice to chat %s", chat_id)
