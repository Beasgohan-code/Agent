"""Agent — inline keyboard callback handling."""

from __future__ import annotations

import logging

from ..ui.screens import SCREENS
from ..ui.theme import Theme
from ..utils.sender import ScreenSender

logger = logging.getLogger(__name__)

STALE_OPTION = "That option is no longer available."


class CallbackHandlers:
    """Routes inline keyboard presses to screens."""

    def __init__(self, sender: ScreenSender, theme: Theme) -> None:
        self._sender = sender
        self._theme = theme

    async def on_callback(self, client, callback_query) -> None:
        data = callback_query.data or ""
        user = callback_query.from_user
        logger.info("Callback %r from user %s", data, getattr(user, "id", None))

        builder = SCREENS.get(data)
        if builder is None:
            logger.warning("Unknown callback data %r", data)
            await self._answer(callback_query, STALE_OPTION, show_alert=True)
            return

        # Answer first so the client's spinner never hangs on a slow edit.
        await self._answer(callback_query)

        message = callback_query.message
        if message is None:
            logger.debug("Callback %r has no message to edit; ignoring.", data)
            return

        screen = builder(user, self._theme)
        if not await self._sender.edit(callback_query, screen):
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            try:
                await self._sender.send(chat_id, screen)
            except Exception:
                logger.exception("Could not re-send screen %r to chat %s", data, chat_id)

    @staticmethod
    async def _answer(callback_query, text: str | None = None, show_alert: bool = False) -> None:
        try:
            await callback_query.answer(text, show_alert=show_alert)
        except Exception:
            logger.debug("Could not answer callback query.", exc_info=True)
