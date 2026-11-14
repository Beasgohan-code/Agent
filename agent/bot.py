"""Agent — client lifecycle and handler wiring."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from pyrogram import Client, filters
from pyrogram.handlers import CallbackQueryHandler, ErrorHandler, MessageHandler

from .config import Settings
from .handlers import CallbackHandlers, CommandHandlers
from .health import HealthMonitor
from .health_server import start_health_server, stop_health_server
from .ui.theme import Theme
from .utils.sender import ScreenSender
from .watchdog import build_watchdog

logger = logging.getLogger(__name__)


class AgentBot:
    """Owns the Telegram client and the startup/shutdown lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.theme = Theme()
        self.health = HealthMonitor(
            degraded_after=max(60.0, settings.watchdog_interval * 3),
            down_after=max(180.0, settings.watchdog_interval * 10),
            failure_threshold=max(3, settings.watchdog_fatal_after - 2),
        )
        #: Set when the watchdog gives up; start.py turns it into exit code 1.
        self.fatal_reason: str | None = None
        self._client: Client | None = None
        self._handlers: list = []

    @property
    def client(self) -> Client | None:
        return self._client

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

    def build(self) -> Client:
        """Create the client and register handlers exactly once."""
        if self._client is not None:
            raise RuntimeError("AgentBot is already initialised; build() may only run once.")

        client = Client(
            name=self.settings.session_name,
            api_id=self.settings.api_id,
            api_hash=self.settings.api_hash,
            bot_token=self.settings.bot_token,
            # Render containers have an ephemeral filesystem and the bot
            # re-authorises cheaply, so no session file is written to disk.
            in_memory=True,
        )
        self._register_handlers(client)
        self._client = client

        logger.info(
            "Client initialised (token=%s, api_id=%s, handlers=%d)",
            self.settings.masked_token,
            self.settings.api_id,
            len(self._handlers),
        )
        return client

    def _register_handlers(self, client: Client) -> None:
        sender = ScreenSender(client, self.theme)
        commands = CommandHandlers(sender, self.theme, monitor=self.health)
        callbacks = CallbackHandlers(sender, self.theme, monitor=self.health)

        self._handlers = [
            MessageHandler(commands.start, filters.command("start") & filters.private),
            MessageHandler(commands.help, filters.command("help") & filters.private),
            CallbackQueryHandler(callbacks.on_callback),
            ErrorHandler(self._on_error),
        ]
        for handler in self._handlers:
            client.add_handler(handler)

    async def _on_error(self, client, exception, handler, update, users, chats) -> None:
        """Catch anything a handler let escape; the bot keeps polling."""
        logger.error(
            "Unhandled %s in %s: %s",
            type(exception).__name__,
            type(handler).__name__,
            exception,
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    async def run(self) -> None:
        """Connect, poll until a stop signal arrives, then disconnect."""
        client = self._client or self.build()

        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)

        logger.info("Starting Agent (token=%s)", self.settings.masked_token)
        try:
            await client.start()
        except Exception:
            logger.exception(
                "Could not connect to Telegram. Check BOT_TOKEN, API_ID, API_HASH "
                "and outbound network access."
            )
            raise

        # A completed handshake is a successful probe.
        self.health.record_success()

        me = client.me
        logger.info(
            "Connected as %s (id=%s)",
            f"@{me.username}" if me.username else me.first_name,
            me.id,
        )

        watchdog = build_watchdog(
            client,
            self.health,
            self.settings,
            on_fatal=lambda: self._request_restart(stop_event),
        )
        watchdog_task = asyncio.create_task(watchdog.run(stop_event), name="agent-watchdog")

        health_runner = None
        if self.settings.health_port:
            health_runner = await start_health_server(self.health, self.settings.health_port)
        else:
            logger.info("No HEALTH_PORT/PORT set: running without an HTTP health endpoint.")

        try:
            await stop_event.wait()
        finally:
            watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog_task
            await stop_health_server(health_runner)
            await self._shutdown(client)

    def _request_restart(self, stop_event: asyncio.Event) -> None:
        """Called by the watchdog when the link is declared dead."""
        self.fatal_reason = "telegram unreachable"
        stop_event.set()

    async def _shutdown(self, client: Client) -> None:
        logger.info("Shutdown requested; disconnecting...")
        try:
            await client.stop()
        except Exception:
            logger.exception("Error while stopping the client.")
        else:
            logger.info("Disconnected. Agent stopped.")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Turn SIGINT/SIGTERM (Render sends SIGTERM) into a graceful stop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - only outside a running loop
        return

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError):  # pragma: no cover
            logger.debug("Signal %s is not supported on this platform.", sig)
