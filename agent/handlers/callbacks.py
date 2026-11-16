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

    def __init__(self, sender: ScreenSender, theme: Theme, monitor=None, *, router=None,
                 active_commands=None) -> None:
        self._sender = sender
        self._theme = theme
        self._monitor = monitor
        #: Modules own their own prefixes; the UI owns the menu screens.
        self._router = router
        #: Callable returning the registered commands, for the help sections.
        self._active_commands = active_commands

    async def on_callback(self, client, callback_query) -> None:
        data = callback_query.data or ""
        user = callback_query.from_user
        if self._monitor is not None:
            self._monitor.record_activity("callback")
        logger.info("Callback received from user %s", getattr(user, "id", None))

        if self._router is not None and self._router.handles(data):
            # Module handlers own their callback acknowledgement.
            dispatched = await self._router.dispatch(client, callback_query)
            if dispatched:
                return

        active = set(self._active_commands()) if self._active_commands is not None else None
        worker_screen = None
        if data.startswith('worker:'):
            from ..ui.workers import callback
            worker_screen = callback(data, user, self._theme, active=active)
        builder = SCREENS.get(data)
        if getattr(self._theme, 'worker_plugins', None) is not None:
            from ..ui.keyboards import CB_HOME, CB_HELP, CB_INFO
            if data not in (CB_HOME, CB_HELP, CB_INFO):
                builder = None  # Old controller category buttons are not worker navigation.
        if builder is None and worker_screen is None:
            logger.warning("Unknown callback control")
            await self._answer(callback_query, STALE_OPTION, show_alert=True)
            return

        # Answer first so the client's spinner never hangs on a slow edit.
        await self._answer(callback_query)

        message = callback_query.message
        if message is None:
            logger.debug("Callback has no message to edit; ignoring.")
            return

        from ..ui.screens import welcome_screen
        options = {}
        if builder is welcome_screen and self._theme.worker_plugins is None:
            from ..ui.bot_identity import bot_username
            options['bot_username'] = await bot_username(client)
        screen = worker_screen if worker_screen is not None else builder(user, self._theme, active=active, **options)
        outcome = await self._sender.edit(callback_query, screen)
        if outcome is None:
            await self._answer(callback_query, "Update not confirmed. Please try again shortly.")
            return
        if outcome is False:
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            try:
                await self._sender.send(chat_id, screen)
            except Exception as error:
                logger.warning("Could not re-send callback screen (%s)", type(error).__name__)

    @staticmethod
    async def _answer(callback_query, text: str | None = None, show_alert: bool = False) -> None:
        try:
            await callback_query.answer(text, show_alert=show_alert)
        except Exception as error:
            logger.debug("Could not answer callback query (%s)", type(error).__name__)
