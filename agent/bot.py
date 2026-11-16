"""Agent — client lifecycle and handler wiring."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions
from pyrogram.handlers import CallbackQueryHandler, ErrorHandler, MessageHandler

from . import __version__
from .config import Settings
from .platform.commands import command_filter
from .modules.moderation.command_cleaning import wrap as wrap_command_cleaning
from .handlers import CallbackHandlers, CommandHandlers
from .keepalive import KeepAlive
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
from .platform.incidents import ErrorIncidents
from .platform.instance import InstanceLease
from .platform.assistant import AssistantLease
from .platform.logbook import LogBook, subscribe
from .platform.menu import publish as publish_menu, reset_menu_button
from .platform.premium import PremiumBook
from .platform.runtime import PluginRuntime
from .platform.startup_cooldown import StartupCooldown
from .platform.voice import VoiceEngine, capability
from .ui.theme import Theme
from .utils.sender import ScreenSender
from .watchdog import build_watchdog


OPTIONAL_STARTUP_TIMEOUT = 30.0
REQUIRED_STARTUP_TIMEOUT = 90.0
SERVICE_SHUTDOWN_TIMEOUT = 5.0

async def _close_optional(label, operation):
    """Bound cooperative optional cleanup; never log raw service exceptions."""
    try:
        await asyncio.wait_for(operation(), timeout=SERVICE_SHUTDOWN_TIMEOUT)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning('#Errors %s cleanup failed (%s); continuing Telegram disconnect.',
                       label, type(error).__name__)


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
        self.theme = Theme(worker_plugins=settings.plugins
                           if (settings.db_scope or '').startswith('clone:') else None)
        self.keepalive = KeepAlive(settings.keepalive_origin)
        self.health = HealthMonitor(
            degraded_after=max(60.0, settings.watchdog_interval * 3),
            down_after=max(180.0, settings.watchdog_interval * 10),
            failure_threshold=max(3, settings.watchdog_fatal_after - 2),
        )
        #: Set when the watchdog gives up; start.py turns it into exit code 1.
        self.fatal_reason: str | None = None
        self._menu_sync_lock = asyncio.Lock()
        self._menu_sync_task = None
        self._commands_dirty = False
        self._commands_closing = False
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
            Database(settings.database_url, scope=settings.db_scope, required=True)
            if settings.database_url
            else None
        )
        db = self.database
        self._telegram_cooldown = StartupCooldown(db) if db is not None else None
        self.incidents = ErrorIncidents(db)
        self.users = UserIndex(settings.data_dir, db=db)
        self.logbook = LogBook(
            settings.data_dir,
            channel_id=settings.log_channel,
            owner_id=settings.owner_id,
            db=db,
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
                assistant_lease=AssistantLease(db) if db is not None else None,
            )
        else:
            self.voice = None
            logger.info("Voice chat disabled: %s", reason)

    @property
    def client(self) -> Client | None:
        return self._client

    def _visible_commands(self):
        """Canonical UI catalogue includes built-ins outside plugin registry."""
        return sorted(set(self.registry.active_commands()) | {'start', 'help', 'ping'})

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
            active_commands=self._visible_commands,
            deeplinks=self.deeplinks,
        )
        callbacks = CallbackHandlers(
            sender,
            self.theme,
            monitor=self.health,
            router=self.actions,
            active_commands=self._visible_commands,
        )

        self._handlers = [
            MessageHandler(commands.start, command_filter(["start", "restart_bot"]) & filters.private),
            MessageHandler(commands.help, command_filter(["help", "h"]) & filters.private),
            MessageHandler(commands.ping, command_filter("ping") & filters.private),
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
        self.modules.incidents = self.incidents
        self.modules.runtime = self.runtime
        self.modules.lease = self.lease
        self._wire_archive(client)
        self.modules.logbook = self.logbook
        self.modules.client = client
        client.agent_context = self.modules

        from .platform.execution import PluginGate, REGISTERING
        from .platform.plugin_access import PluginAccess
        self.plugin_access = PluginAccess(self.database, owner_id=self.settings.owner_id)
        self.plugin_gate = PluginGate(self.plugin_access, self.runtime, self.modules.jobs)
        self.plugin_access.cleanup_callback = self.plugin_gate.cleanup
        self.modules.plugin_access = self.plugin_access
        self.modules.plugin_gate = self.plugin_gate
        self.actions.gate = self.plugin_gate
        self.deeplinks.gate = self.plugin_gate

        self._modules = select(self.settings.plugins)
        for slug in unknown(self.settings.plugins):
            logger.warning("PLUGINS names %r, which is not a module here; ignoring it", slug)
        skipped = not_selected(self.settings.plugins)
        if skipped:
            logger.info("Plugins not selected (compile in, register nothing): %s", ", ".join(skipped))
        built = []
        for module in self._modules:
            from .platform.policy import PROTECTED_PLUGINS
            token = REGISTERING.set(module.MANIFEST.slug)
            action_routes = dict(self.actions._routes)
            link_routes = dict(self.deeplinks._routes)
            try:
                manifest, handlers = module.build(self.modules)
                self.registry.register(manifest, handlers)
                built.append(module)
            except Exception:
                self.actions._routes = action_routes
                self.deeplinks._routes = link_routes
                if module.MANIFEST.slug in PROTECTED_PLUGINS:
                    raise  # never pretend a missing mandatory system is healthy
                logger.exception("Optional plugin %s failed to build; core remains available.", module.MANIFEST.slug)
            finally:
                REGISTERING.reset(token)
        self._modules = tuple(built)

        # Never import third-party Python into the token-bearing bot process.
        # Staging/review is not isolation. External execution stays disabled until
        # a capability-scoped process boundary exists.

        # Build and track dormant handlers too, so persisted-off plugins can
        # be enabled without restarting. Attach only enabled handlers below.
        scopes = {c: m.scope for m in self.registry.manifests() for c in m.commands}
        owners = {c: m.slug for m in self.registry.manifests() for c in m.commands}
        for command in self.registry.active_commands():
            callback = self.registry.handler_for(command)
            if callback is None:  # pragma: no cover - active_commands guarantees this
                continue
            chat_filter = _scope_filter(scopes.get(command, "private"))
            callback = self.plugin_gate.wrap(owners.get(command, "unknown"), callback)
            callback = wrap_command_cleaning(self.modules, callback)
            handler = MessageHandler(callback, command_filter(command) & chat_filter)
            self._handlers.append(handler)
            self.runtime.track(owners.get(command, "unknown"), handler, 0)

        # Some modules also need to see updates that are not commands (anti-spam,
        # filters, joins/leaves). Each gets its own handler group: pyrogram runs
        # at most one handler per group per update, so sharing a group would let
        # one watcher swallow another's updates.
        for module in self._modules:
            factory = getattr(module, "extra_handlers", None)
            slug = module.MANIFEST.slug
            if factory is None:
                continue
            for watcher in factory(self.modules):
                watcher.callback = self.plugin_gate.wrap(slug, watcher.callback, silent=True)
                self._watchers.append(watcher)
                self.runtime.track(slug, watcher, len(self._watchers))

        for manifest in self.registry.manifests():
            if self.runtime.wants_disabled(manifest.slug):
                self.registry.disable(manifest.slug)
        dormant = self.runtime.dormant_handler_ids()
        for handler in self._handlers:
            if id(handler) not in dormant:
                client.add_handler(handler)
        for index, watcher in enumerate(self._watchers, start=1):
            if id(watcher) not in dormant:
                client.add_handler(watcher, group=index)
        self.runtime.attach(client)
        self.runtime.change_hook = self._schedule_command_sync
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
        incident = await self.incidents.capture(exception, handler)
        if incident['notify']:
            self.events.emit("error", incident=incident['incident_id'],
                error_type=incident['error_type'], handler=incident['handler'],
                occurrences=incident['occurrences'], saved=incident['saved'],
                location="; ".join(incident['frames']))
        logger.error("Unhandled %s in %s; incident=%s (raw exception text withheld)",
                     incident['error_type'], incident['handler'], incident['incident_id'])

    async def run(self) -> None:
        """Expose process liveness before waiting for a rolling-deploy handover."""
        runner = None
        keepalive_task = None
        try:
            if self.settings.health_port:
                runner = await start_health_server(
                    self.health, self.settings.health_port, extra=self._health_detail
                )
            else:
                logger.info("No HEALTH_PORT/PORT set: running without an HTTP health endpoint.")
            if runner is not None and self.keepalive.target:
                keepalive_task = asyncio.create_task(self.keepalive.run(), name="public-keepalive")
            await self._run()
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await keepalive_task
            plugin_watch = getattr(self, "_plugin_watch", None)
            if plugin_watch is not None:
                plugin_watch.cancel()
                with suppress(asyncio.CancelledError):
                    await plugin_watch
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

    def _startup_phase(self, phase: str) -> None:
        self.startup_phase = phase
        logger.info('Startup phase: %s', phase)

    async def _startup_step(self, phase, operation):
        """Bound required network stages without exposing connection details."""
        self._startup_phase(phase)
        try:
            return await asyncio.wait_for(operation(), timeout=REQUIRED_STARTUP_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except FloodWait:
            # The Telegram connector owns server-directed cooldown/retry.
            raise
        except Exception as error:
            self.fatal_reason = f'Startup failed at {phase} ({type(error).__name__}); check hosting configuration and connectivity'
            logger.error('#Errors %s', self.fatal_reason)
            raise RuntimeError(self.fatal_reason) from None

    async def _connect_telegram(self, client, stop_event):
        """Respect server-directed FloodWait without crashing into a restart loop.

        Each handshake has its own deadline; cooldown intentionally is not
        covered by that deadline. Lease heartbeat continues while waiting.
        """
        self._telegram_started = False
        cooldown = getattr(self, '_telegram_cooldown', None)
        if cooldown is not None:
            seconds = await self._startup_step('telegram-cooldown-load', cooldown.remaining)
            if seconds > 0:
                self._startup_phase('telegram-floodwait')
                logger.warning('Restored Telegram startup cooldown: waiting %.1f seconds before connecting.', seconds)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=seconds)
                except asyncio.TimeoutError:
                    pass
                else:
                    return False
        while not stop_event.is_set():
            try:
                connecting = asyncio.create_task(self._startup_step('telegram-connect', client.start))
                stopping = asyncio.create_task(stop_event.wait())
                try:
                    await asyncio.wait((connecting, stopping), return_when=asyncio.FIRST_COMPLETED)
                    # Stop/lease loss wins even when both finish in one loop tick.
                    if stop_event.is_set():
                        return False
                    connecting.result()  # Propagate FloodWait to cooldown handling.
                    self._telegram_started = True
                    return True
                finally:
                    for task in (connecting, stopping):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(connecting, stopping, return_exceptions=True)
            except FloodWait as error:
                seconds = max(1, int(error.value) + 1)
                if cooldown is not None:
                    await self._startup_step('telegram-cooldown-save', lambda: cooldown.extend(seconds))
                self._startup_phase('telegram-floodwait')
                logger.warning('Telegram startup rate-limited: waiting %s seconds before retry; do not restart repeatedly.', seconds)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=seconds)
                except asyncio.TimeoutError:
                    continue
                return False
        return False

    async def _run(self) -> None:
        """Connect only after obtaining exclusive ownership of this bot token."""
        if self.database is None:
            self.fatal_reason = "PostgreSQL is required: DATABASE_URL is missing or invalid"
            logger.critical(self.fatal_reason)
            return
        if self.database is not None:
            if await self._startup_step('database-connect', self.database.connect):
                await self._startup_step('database-load', self.database.load)
                if self.database.load_error:
                    self.fatal_reason = "Required PostgreSQL state could not be loaded"
                    logger.critical(self.fatal_reason)
                    return
                try:
                    await self._startup_step('log-destination-load', self.logbook.hydrate)
                except Exception:
                    self.fatal_reason = "PostgreSQL log destination could not be loaded"
                    logger.critical(self.fatal_reason)
                    return
                # These stores were built in __init__, before the database was
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
            else:
                # The deployment said the database is the source of truth; two
                # competing ones (database and files) are worse than not starting.
                self.fatal_reason = (
                    "DATABASE_URL is required but unusable; check database connectivity and credentials in hosting settings"
                )
                logger.critical(self.fatal_reason)
                return


        self._startup_phase('handler-build')
        client = self._client or self.build()

        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)
        self.runtime.restart_hook = stop_event.set

        # Two copies of one token would answer every update twice. Take the
        # lease first; wait for a departing deploy, then give up rather than
        # double-serve.
        self._startup_phase('token-lease')
        if not await self._acquire_lease(stop_event):
            if stop_event.is_set():
                return
            self.fatal_reason = "instance lease held by another process"
            logger.critical(
                "Another instance holds the lease for this bot; not connecting."
            )
            return

        heartbeat_task = self.lease.start_heartbeat(stop_event)
        watchdog_task = None
        try:
            self._plugin_watch = asyncio.create_task(self.plugin_gate.watch(stop_event), name="plugin-reconciliation")
            logger.info("Starting Meiko (token=%s)", self.settings.masked_token)
            try:
                if not await self._connect_telegram(client, stop_event):
                    return
            except Exception:
                logger.exception(
                    "Could not connect to Telegram. Check BOT_TOKEN, API_ID, API_HASH "
                    "and outbound network access."
                )
                # start() may have opened a session before failing. Disconnect it
                # before the outer wrapper releases exclusive token ownership.
                raise

            # The primary bot is connected now. Optional services must not hide
            # this milestone or delay health readiness indefinitely.
            self.health.record_success()
            self.events.emit("start", version=__version__)
            logger.info('Main Telegram client connected; starting optional services with bounded waits.')
            self._startup_phase('optional-services')
            await self._start_optional_services()
            self._startup_phase('command-menu-sync')

            # Make Telegram's own command menu match what this process actually
            # registered — a disabled plugin must not linger in the menu either.
            await self._sync_commands(client, reset_button=True)

            self._startup_phase('running')
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

            await stop_event.wait()
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
            heartbeat_task.cancel()
            tasks = [heartbeat_task] + ([watchdog_task] if watchdog_task is not None else [])
            # A failed monitoring task must not skip Telegram disconnect.
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._cleanup_services(client)

    async def _start_optional_services(self):
        """Bound optional integrations; neither may block the main bot forever."""
        storage = getattr(self.modules, 'storage', None)
        recover = getattr(storage, 'start_archive_recovery', None)
        if recover is not None:
            recover()
        # Start the voice engine after the bot is up: a failure there must not
        # take the command surface down with it.
        if self.voice is not None:
            try:
                await asyncio.wait_for(self.voice.start(), timeout=OPTIONAL_STARTUP_TIMEOUT)
            except Exception:  # noqa: BLE001 - the music commands report the reason
                logger.exception("Voice chat engine failed to start; the player is inert.")

        # Clones that were running when this process last stopped are started
        # again here, one at a time: a revoked token must not take the main bot
        # down with it.
        clones = getattr(self.modules, "clones", None)
        if clones is not None:
            try:
                await asyncio.wait_for(clones.restore(), timeout=OPTIONAL_STARTUP_TIMEOUT)
            except Exception:  # noqa: BLE001 - clones are a feature, not the bot
                logger.exception("Could not restore clones; continuing without them.")
            # Then keep watching: a clone that drops its connection is restarted
            # with a capped backoff, instead of being reported as up forever.
            if getattr(clones, "watch", None) is not None and self.settings.clone_limit:
                self._supervisor = asyncio.create_task(
                    clones.watch(self.settings.watchdog_interval), name="clone-supervisor"
                )


    async def _sync_commands(self, client, *, reset_button=False):
        async with self._menu_sync_lock:
            if self._commands_closing:
                return
            if reset_button:
                await reset_menu_button(client)
            if not self.settings.sync_commands:
                return
            try:
                scopes = {command: manifest.scope for manifest in self.registry.manifests()
                          for command in manifest.commands}
                scopes.update({command: "private" for command in ("start", "help", "ping")})
                await publish_menu(client, ["start", "help", "ping", *self.registry.active_commands()],
                                   command_scopes=scopes)
            except Exception:
                logger.warning("Command-list sync failed; active handlers are unchanged.")

    def _schedule_command_sync(self):
        if (self._commands_closing or not self.settings.sync_commands
                or not getattr(self._client, "is_connected", False)):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._commands_dirty = True
        if self._menu_sync_task is not None and not self._menu_sync_task.done():
            return
        async def sync():
            while self._commands_dirty and not self._commands_closing:
                self._commands_dirty = False
                await asyncio.sleep(0.1)
                await self._sync_commands(self._client)
        self._menu_sync_task = loop.create_task(sync(), name="telegram-command-sync")

    async def _cleanup_services(self, client) -> None:
        """Optional shutdown failures must not prevent Telegram disconnect."""
        self._commands_closing = True
        command_sync = getattr(self, "_menu_sync_task", None)
        if command_sync is not None:
            command_sync.cancel()
            await asyncio.gather(command_sync, return_exceptions=True)
            self._menu_sync_task = None
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
            await _close_optional('Voice', self.voice.shutdown)
        clones = getattr(self.modules, 'clones', None)
        if clones is not None:
            await _close_optional('Clones', clones.stop_all)
        for name in ('verifier', 'jobs', 'storage'):
            service = getattr(self.modules, name, None)
            shutdown = getattr(service, 'shutdown', None)
            if shutdown is not None:
                await _close_optional(name, shutdown)
        # Emit while connected, then drain only this bot's delivery tasks.
        # A bounded log-channel failure must never prevent Telegram shutdown.
        try:
            if getattr(self, '_telegram_started', True) and not getattr(self, "_stop_event_emitted", False):
                self._stop_event_emitted = True
                self.events.emit("stop")
            await self.logbook.close(timeout=5.0)
        except Exception:
            logger.warning("Log-channel shutdown failed; continuing Telegram disconnect.")
        finally:
            await self._shutdown(client)

    def _health_detail(self) -> dict:
        """Extra fields for ``/health``: the lease and the plugin states."""
        disabled = [row["slug"] for row in self.runtime.state() if not row["enabled"]]
        return {
            "startup_phase": getattr(self, 'startup_phase', 'initializing'),
            "instance": self.lease.state(),
            "plugins_disabled": disabled,
            "events": self.events.count(),
            "keepalive": self.keepalive.snapshot(),
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
            logger.info("Disconnected. Meiko stopped.")


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
