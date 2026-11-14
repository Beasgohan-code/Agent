"""Agent — command handlers."""

from __future__ import annotations

import logging

from ..ui.screens import help_screen, welcome_screen
from ..ui.theme import Theme
from ..utils.sender import ScreenSender

logger = logging.getLogger(__name__)

FAILURE_NOTICE = "Something went wrong on my side. Please try again in a moment."


class CommandHandlers:
    """``/start`` and ``/help``."""

    def __init__(self, sender: ScreenSender, theme: Theme) -> None:
        self._sender = sender
        self._theme = theme

    async def start(self, client, message) -> None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        logger.info("/start from user %s", user_id)
        await self._show(client, message, welcome_screen(message.from_user, self._theme), "welcome")

    async def help(self, client, message) -> None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        logger.info("/help from user %s", user_id)
        await self._show(client, message, help_screen(message.from_user, self._theme), "help")

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
