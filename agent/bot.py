"""Agent — client lifecycle and handler wiring."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions
from pyrogram.handlers import CallbackQueryHandler, ErrorHandler, MessageHandler

from . import __version__
from .config import Settings
from .handlers import CallbackHandlers, CommandHandlers
from .health import HealthMonitor
from .modules import MODULES
from .platform.context import ModuleContext
from .platform.manifest import PluginRegistry
from .health_server import start_health_server, stop_health_server
from .platform.audience import UserIndex
from .platform.events import EventLog
from .platform.instance import InstanceLease
from .platform.logbook import LogBook, subscribe
from .platform.menu import publish as publish_menu, reset_menu_button
from .platform.runtime import PluginRuntime
from .ui.theme import Theme
from .utils.sender import ScreenSender
from .watchdog import build_watchdog


def _scope_filter(scope: str):
    """Where a module's commands may run, as declared by its manifest."""
    if scope == "group":
        return filters.group
    if scope == "all":
        return filters.all
    return filters.private

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
        self.modules: ModuleContext | None = None
        self.registry = PluginRegistry()
        self.events = EventLog()
        self.users = UserIndex(settings.data_dir)
        #: Videl1-style log channel: every event, hashtag-tagged, or owner DMs.
        self.logbook = LogBook(
            settings.data_dir,
            channel_id=settings.log_channel,
            owner_id=settings.owner_id,
        )
        subscribe(self.events, self.logbook)
        #: One lease per bot token: two live copies would answer every update twice.
        self.lease = InstanceLease(settings.data_dir / "instance.lock")
        self.runtime = PluginRuntime(
            self.registry, state_path=settings.data_dir / "plugins.json"
        )

    @property
    def client(self) -> Client | None:
        return self._client

    @property
    def handler_count(self) -> int:
        return len(self._handlers) + len(getattr(self, "_watchers", []))

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
            # Every reply this bot writes is HTML (bold, code, blockquotes and
            # the monospace tables in agent.ui.tables). Without a client-level
            # parse mode pyrogram sends those tags as literal text, which is
            # what made plain replies look broken.
            parse_mode=ParseMode.HTML,
            # A command answer never needs a link preview balloon.
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        self._register_handlers(client)
        self._client = client

        logger.info(
            "Client initialised (token=%s, handlers=%d)",
            self.settings.masked_token,
            self.handler_count,
        )
        return client

    def _register_handlers(self, client: Client) -> None:
        sender = ScreenSender(client, self.theme)
        #: Plain-message watchers (anti-spam) run in their own handler group so
        #: they can never shadow a command handler.
        self._watchers = []
        commands = CommandHandlers(
            sender, self.theme, monitor=self.health, events=self.events, users=self.users
        )
        callbacks = CallbackHandlers(sender, self.theme, monitor=self.health)

        self._handlers = [
            MessageHandler(commands.start, filters.command(["start", "restart_bot"]) & filters.private),
            MessageHandler(commands.help, filters.command(["help", "h"]) & filters.private),
            MessageHandler(commands.ping, filters.command("ping") & filters.private),
            CallbackQueryHandler(callbacks.on_callback),
            ErrorHandler(self._on_error),
        ]

        # --- feature modules (plugins) -----------------------------------
        # Shared services are built once and handed to every module. They are
        # attached *before* the first module builds: a module reads its services
        # from the context while building, so attaching afterwards leaves every
        # module holding None and the runtime commands answering "unavailable".
        self.modules = ModuleContext.build(
            self.settings, self.theme, sender, root=self.settings.data_dir
        )
        self.modules.registry = self.registry
        self.modules.events = self.events
        self.modules.runtime = self.runtime
        self.modules.lease = self.lease
        self.modules.logbook = self.logbook
        self.modules.client = client

        for module in MODULES:
            manifest, handlers = module.build(self.modules)
            self.registry.register(manifest, handlers)

        # A plugin disabled in a previous run stays off, and registers nothing.
        for manifest in self.registry.manifests():
            if self.runtime.wants_disabled(manifest.slug):
                self.registry.disable(manifest.slug)

        # Only *enabled* plugins contribute handlers. A disabled plugin
        # registers nothing at all, which is the lifecycle rule that matters.
        scopes = {c: m.scope for m in self.registry.manifests() for c in m.commands}
        owners = {c: m.slug for m in self.registry.manifests() for c in m.commands}
        for command in self.registry.active_commands():
            callback = self.registry.handler_for(command)
            if callback is None:  # pragma: no cover - active_commands guarantees this
                continue
            chat_filter = _scope_filter(scopes.get(command, "private"))
            handler = MessageHandler(callback, filters.command(command) & chat_filter)
            self._handlers.append(handler)
            self.runtime.track(owners.get(command, "unknown"), handler, 0)

        # Some modules also need to see updates that are not commands (anti-spam,
        # filters, joins/leaves). Each gets its own handler group: pyrogram runs
        # at most one handler per group per update, so sharing a group would let
        # one watcher swallow another's updates.
        for module in MODULES:
            factory = getattr(module, "extra_handlers", None)
            slug = module.MANIFEST.slug
            if factory is None or not self.registry.is_enabled(slug):
                continue
            for watcher in factory(self.modules):
                self._watchers.append(watcher)
                self.runtime.track(slug, watcher, len(self._watchers))

        for handler in self._handlers:
            client.add_handler(handler)
        for index, watcher in enumerate(self._watchers, start=1):
            client.add_handler(watcher, group=index)
        self.runtime.attach(client)
        self.logbook.client = client

        enabled = [m.slug for m in self.registry.manifests() if self.registry.is_enabled(m.slug)]
        logger.info(
            "Modules active: %s (%d commands)",
            ", ".join(enabled) or "none",
            len(self.registry.active_commands()),
        )

    async def _on_error(self, client, exception, handler, update, users, chats) -> None:
        """Catch anything a handler let escape; the bot keeps polling."""
        # ``kind`` is the event's own parameter, so the field is named separately.
        self.events.emit(
            "error", error_type=type(exception).__name__, detail=str(exception)[:200]
        )
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
        self.runtime.restart_hook = stop_event.set

        # Two copies of one token would answer every update twice. Take the
        # lease first; wait for a departing deploy, then give up rather than
        # double-serve.
        if not await self.lease.acquire():
            self.fatal_reason = "instance lease held by another process"
            logger.critical(
                "Another instance holds the lease for this bot; not connecting."
            )
            return

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
        self.events.emit("start", version=__version__)

        # Make Telegram's own command menu match what this process actually
        # registered — a disabled plugin must not linger in the menu either.
        if self.settings.sync_commands:
            try:
                await reset_menu_button(client)
                await publish_menu(
                    client, ["start", "help", "ping", *self.registry.active_commands()]
                )
            except Exception:  # noqa: BLE001 - menu cosmetics never stop the bot
                logger.exception("Command menu sync failed; continuing without it.")

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
        heartbeat_task = self.lease.start_heartbeat(stop_event)

        health_runner = None
        if self.settings.health_port:
            health_runner = await start_health_server(
                self.health, self.settings.health_port, extra=self._health_detail
            )
        else:
            logger.info("No HEALTH_PORT/PORT set: running without an HTTP health endpoint.")

        try:
            await stop_event.wait()
        finally:
            watchdog_task.cancel()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog_task
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            await stop_health_server(health_runner)
            await self._shutdown(client)
            await self.lease.stop_heartbeat()
            # Releasing lets a replacement process start immediately (this is
            # what makes /restart a fast handover rather than a 60s timeout).
            self.lease.release()
            self.events.emit("stop")

    def _health_detail(self) -> dict:
        """Extra fields for ``/health``: the lease and the plugin states."""
        disabled = [row["slug"] for row in self.runtime.state() if not row["enabled"]]
        return {
            "instance": self.lease.state(),
            "plugins_disabled": disabled,
            "events": self.events.count(),
        }

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
