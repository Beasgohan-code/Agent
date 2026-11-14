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
from .modules import not_selected, select, unknown
from .platform.context import ModuleContext
from .platform.manifest import PluginRegistry
from .health_server import start_health_server, stop_health_server
from .platform.actions import ActionRouter
from .platform.deeplinks import DeepLinkRouter
from .platform.audience import UserIndex
from .platform.db import Database
from .platform.events import EventLog
from .platform.instance import InstanceLease
from .platform.logbook import LogBook, subscribe
from .platform.menu import publish as publish_menu, reset_menu_button
from .platform.premium import PremiumBook
from .platform.runtime import PluginRuntime
from .platform.voice import VoiceEngine, capability
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
        #: PostgreSQL, when the deployment provides DATABASE_URL. Connected (and
        #: loaded) in run(), before the client starts, so the stores are built
        #: against the database rather than filling up from files first.
        # Every row this instance writes is prefixed with its scope, so a
        # clone's ``runtime`` can never overwrite the main bot's.
        self.database = (
            Database(settings.database_url, scope=settings.db_scope, required=settings.db_required)
            if settings.database_url
            else None
        )
        db = self.database
        self.users = UserIndex(settings.data_dir, db=db)
        self.logbook = LogBook(
            settings.data_dir,
            channel_id=settings.log_channel,
            owner_id=settings.owner_id,
        )
        subscribe(self.events, self.logbook)
        #: One lease per bot token: two live copies would answer every update twice.
        self.lease = InstanceLease(settings.data_dir / "instance.lock", db=db)
        self.runtime = PluginRuntime(
            self.registry, state_path=settings.data_dir / "plugins.json", db=db
        )
        #: Module-owned callback prefixes (member verification today).
        self.actions = ActionRouter()
        #: Module-owned ``/start <payload>`` prefixes (share links today).
        self.deeplinks = DeepLinkRouter()
        #: Premium membership and the tier allowances the modules enforce.
        self.premium = PremiumBook(settings.data_dir, db=db)
        #: Voice-chat streaming is optional: without a session string there is no
        #: engine and the music module registers nothing.
        ok, reason = capability(settings.session_string)
        if ok:
            self.voice = VoiceEngine(
                session_string=settings.session_string or "",
                api_id=settings.api_id,
                api_hash=settings.api_hash,
            )
        else:
            self.voice = None
            logger.info("Voice chat disabled: %s", reason)

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
            sender,
            self.theme,
            monitor=self.health,
            events=self.events,
            users=self.users,
            start_image=self.settings.start_image,
            active_commands=self.registry.active_commands,
            deeplinks=self.deeplinks,
        )
        callbacks = CallbackHandlers(
            sender,
            self.theme,
            monitor=self.health,
            router=self.actions,
            active_commands=self.registry.active_commands,
        )

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
            self.settings,
            self.theme,
            sender,
            root=self.settings.data_dir,
            db=self.database,
        )
        self.modules.registry = self.registry
        self.modules.actions = self.actions
        self.modules.deeplinks = self.deeplinks
        self.modules.voice = self.voice
        self.modules.premium = self.premium
        self.modules.events = self.events
        self.modules.runtime = self.runtime
        self.modules.lease = self.lease
        self._wire_archive(client)
        self.modules.logbook = self.logbook
        self.modules.client = client

        self._modules = select(self.settings.plugins)
        for slug in unknown(self.settings.plugins):
            logger.warning("PLUGINS names %r, which is not a module here; ignoring it", slug)
        skipped = not_selected(self.settings.plugins)
        if skipped:
            logger.info("Plugins not selected (compile in, register nothing): %s", ", ".join(skipped))
        for module in self._modules:
            manifest, handlers = module.build(self.modules)
            self.registry.register(manifest, handlers)

        # Never import third-party Python into the token-bearing bot process.
        # Staging/review is not isolation. External execution stays disabled until
        # a capability-scoped process boundary exists.

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
        for module in self._modules:
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

    def _wire_archive(self, client: Client) -> None:
        """Let the vault put bytes in the storage channel, when one is configured.

        The uploader is a closure over the client, not the store holding a
        client: the store stays a storage layer, and a deployment without
        ``STORAGE_CHANNEL`` simply keeps its files on disk.
        """
        channel = self.settings.storage_channel
        storage = getattr(self.modules, "storage", None)
        if channel is None or storage is None or not hasattr(storage, "attach_archive"):
            if storage is not None and channel is None:
                logger.info(
                    "STORAGE_CHANNEL is not set: vault files stay on this host's disk."
                )
            return

        async def uploader(path, name: str) -> str:
            sent = await client.send_document(
                chat_id=channel, document=str(path), file_name=name
            )
            document = getattr(sent, "document", None)
            return getattr(document, "file_id", "") or ""

        storage.attach_archive(uploader)
        logger.info("Vault files are archived to the storage channel %s", channel)

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
        """Expose process liveness before waiting for a rolling-deploy handover."""
        runner = None
        try:
            if self.settings.health_port:
                runner = await start_health_server(
                    self.health, self.settings.health_port, extra=self._health_detail
                )
            else:
                logger.info("No HEALTH_PORT/PORT set: running without an HTTP health endpoint.")
            await self._run()
        finally:
            # Each cleanup must run even if an earlier cleanup fails. Release is
            # owner-checked; never delete another container's lease.
            try:
                await stop_health_server(runner)
            finally:
                try:
                    await self.lease.stop_heartbeat()
                finally:
                    try:
                        await self.lease.release_async()
                    finally:
                        if self.database is not None:
                            await self.database.close()

    async def _acquire_lease(self, stop_event) -> bool:
        """A web replacement may wait while Render retires its predecessor."""
        while not stop_event.is_set():
            attempt = asyncio.create_task(self.lease.acquire())
            stopped = asyncio.create_task(stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (attempt, stopped), return_when=asyncio.FIRST_COMPLETED
                )
                if stopped in done:
                    return False
                if attempt.result():
                    return True
                if not self.settings.health_port:
                    return False
                logger.warning("Standby: waiting for exclusive database lease ownership.")
                # An unavailable database may fail immediately. Do not spin and
                # hammer PostgreSQL while waiting for it to recover.
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            finally:
                for task in (attempt, stopped):
                    task.cancel()
                for task in (attempt, stopped):
                    with suppress(asyncio.CancelledError):
                        await task
        return False

    async def _run(self) -> None:
        """Connect only after obtaining exclusive ownership of this bot token."""
        if self.settings.db_required and self.database is None:
            self.fatal_reason = "DB_REQUIRED is enabled but DATABASE_URL is missing or invalid"
            logger.critical(self.fatal_reason)
            return
        if self.database is not None:
            if await self.database.connect():
                await self.database.load()
                if self.settings.db_required and self.database.load_error:
                    self.fatal_reason = "Required PostgreSQL state could not be loaded"
                    logger.critical(self.fatal_reason)
                    return
                # These three were built in __init__, before the database was
                # readable; re-read them so a deploy starts from the stored state
                # rather than from last boot's files.
                for store in (
                    self.users,
                    self.premium,
                    self.runtime,
                    getattr(self.modules, "storage", None),
                ):
                    hydrate = getattr(store, "hydrate", None)
                    if hydrate is not None:
                        hydrate()
            elif self.settings.db_required:
                # The deployment said the database is the source of truth; two
                # competing ones (database and files) are worse than not starting.
                self.fatal_reason = (
                    "DATABASE_URL is required but unusable: "
                    f"{self.database.error or 'no reason given'}"
                )
                logger.critical(self.fatal_reason)
                return
            else:
                logger.warning(
                    "Continuing with JSON files: DATABASE_URL is set but unusable (%s).",
                    self.database.error or "no reason given",
                )

        client = self._client or self.build()

        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)
        self.runtime.restart_hook = stop_event.set

        # Two copies of one token would answer every update twice. Take the
        # lease first; wait for a departing deploy, then give up rather than
        # double-serve.
        if not await self._acquire_lease(stop_event):
            if stop_event.is_set():
                return
            self.fatal_reason = "instance lease held by another process"
            logger.critical(
                "Another instance holds the lease for this bot; not connecting."
            )
            return

        heartbeat_task = self.lease.start_heartbeat(stop_event)
        logger.info("Starting Agent (token=%s)", self.settings.masked_token)
        try:
            await client.start()
        except Exception:
            logger.exception(
                "Could not connect to Telegram. Check BOT_TOKEN, API_ID, API_HASH "
                "and outbound network access."
            )
            # start() may have opened a session before failing. Disconnect it
            # before the outer wrapper releases exclusive token ownership.
            await self._shutdown(client)
            raise

        # Start the voice engine after the bot is up: a failure there must not
        # take the command surface down with it.
        if self.voice is not None:
            try:
                await self.voice.start()
            except Exception:  # noqa: BLE001 - the music commands report the reason
                logger.exception("Voice chat engine failed to start; the player is inert.")

        # Clones that were running when this process last stopped are started
        # again here, one at a time: a revoked token must not take the main bot
        # down with it.
        clones = getattr(self.modules, "clones", None)
        if clones is not None:
            try:
                await clones.restore()
            except Exception:  # noqa: BLE001 - clones are a feature, not the bot
                logger.exception("Could not restore clones; continuing without them.")
            # Then keep watching: a clone that drops its connection is restarted
            # with a capped backoff, instead of being reported as up forever.
            if getattr(clones, "watch", None) is not None and self.settings.clone_limit:
                self._supervisor = asyncio.create_task(
                    clones.watch(self.settings.watchdog_interval), name="clone-supervisor"
                )

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

        try:
            await stop_event.wait()
        finally:
            watchdog_task.cancel()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog_task
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            await self._cleanup_services(client)
            self.events.emit("stop")

    async def _cleanup_services(self, client) -> None:
        """Optional shutdown failures must not prevent Telegram disconnect."""
        supervisor = getattr(self, "_supervisor", None)
        if supervisor is not None:
            supervisor.cancel()
            try:
                await supervisor
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Clone supervisor failed during shutdown.")
            self._supervisor = None
        if self.voice is not None:
            try:
                await self.voice.shutdown()
            except Exception:
                logger.exception("Voice shutdown failed; continuing cleanup.")
        clones = getattr(self.modules, "clones", None)
        if clones is not None:
            try:
                await clones.stop_all()
            except Exception:
                logger.exception("Clone shutdown failed; continuing cleanup.")
        await self._shutdown(client)

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
