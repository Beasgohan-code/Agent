"""Running clones: one client each, started on demand and stopped cleanly.

A clone is a second bot answering its own token, so it must never share a
process's polling loop or its session file. Each one gets:

* its own session name, so two clones cannot collide on disk;
* its own data directory (``data/clones/<bot_id>``), so a clone's vault and
  premium ledger cannot be mistaken for the main bot's;
* its own :class:`agent.bot.AgentBot`, which is what makes a clone behave like
  this bot rather than like a mini version of it.

What this module refuses to fake: a clone that cannot connect is an error with
Telegram's own sentence, and a clone that dies is removed from the running set
instead of being reported as up.
"""

from __future__ import annotations

import asyncio
import logging
import hashlib
from dataclasses import replace
from typing import Callable

from . import lifecycle, profiles
from .catalog import ALLOWED_PLUGINS
from .lifecycle import State, WorkerState
from .store import Clone, CloneStore

logger = logging.getLogger(__name__)


class CloneError(RuntimeError):
    """A clone could not be started, with a sentence the owner can act on."""


class CloneManager:
    """Owns the running clients, keyed by bot id."""

    def __init__(
        self,
        settings,
        store: CloneStore,
        factory: Callable[[object], object] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._factory = factory or _default_factory
        from .configuration import CloneConfigurationWriter
        self.configuration = CloneConfigurationWriter(store, self.settings_for, controller_owner_id=settings.owner_id)
        store.configuration = self.configuration
        #: bot_id -> (bot, client, username)
        self._running: dict[int, tuple[object, object, str]] = {}
        #: What each worker is doing, including the ones that are not running.
        self._states = lifecycle.Registry()
        self._lock = asyncio.Lock()
        self.eligible = None
        self._lease_monitors = {}
        self._configuration_retry: dict[int, int] = {}
        self._running_revisions: dict[int, int] = {}
        self._reconciliation_locks: dict[int, asyncio.Lock] = {}

    # -- settings ---------------------------------------------------------
    def settings_for(self, clone: Clone):
        """The settings a clone runs with: its token, directories and profile.

        Optional features come from a guided selection or legacy profile;
        mandatory core is added by Agent's module selector. Credentials and
        resource destinations never fall through to the parent's values.
        """
        if clone.selected_plugins and (
            len(clone.selected_plugins) != 1
            or any(name not in ALLOWED_PLUGINS for name in clone.selected_plugins)
        ):
            raise CloneError("The guided clone selection is unsupported. Restart setup.")
        if clone.selected_plugins == ("ai_agent",) and (not clone.ai_api_key or not clone.ai_model):
            raise CloneError("AI Agent requires this clone's own provider key and model.")
        if clone.selected_plugins == ("music",):
            if not clone.assistant_session or not self._settings.database_url:
                raise CloneError("Music requires its own assistant session and PostgreSQL.")
            from .assistant import validate_session
            try:
                validate_session(clone.assistant_session)
            except Exception:
                raise CloneError("The assistant session is unsupported. Restart setup.") from None
        return replace(
            self._settings,
            bot_token=clone.token,
            bot_id=clone.bot_id,
            link_secret=hashlib.sha256(clone.token.encode()).hexdigest(),
            session_name=f"agent_clone_{clone.bot_id}",
            data_dir=self._settings.data_dir / "clones" / str(clone.bot_id),
            # The recorded token sender owns this bot tenant, not the parent.
            owner_id=clone.owner_id,
            log_channel=clone.log_channel,
            storage_channel=clone.storage_channel,
            # Never share the deployment's user-session credential with clones.
            session_string=clone.assistant_session if clone.selected_plugins == ("music",) else None,
            ai_api_key=clone.ai_api_key if clone.selected_plugins == ("ai_agent",) else None,
            ai_model=clone.ai_model if clone.selected_plugins == ("ai_agent",) else None,
            health_port=None,
            # Its own rows in PostgreSQL. Without this every clone would write
            # the same ``runtime``/``premium``/``chats`` documents as the main
            # bot and the last writer would silently win.
            db_scope=f"clone:{clone.bot_id}",
            plugins=tuple(name for name in clone.selected_plugins if name in ALLOWED_PLUGINS)
            if clone.selected_plugins else profiles.plugins_for(clone.profile, self._settings),
        )

    # -- lifecycle --------------------------------------------------------
    def state(self, bot_id: int) -> WorkerState:
        """The worker's state; a stored clone that was never started is stopped."""
        if int(bot_id) in self._states:
            return self._states.get(bot_id)
        return WorkerState(state=State.STOPPED)

    def status(self) -> tuple[tuple[Clone, WorkerState], ...]:
        """Every stored clone with its state, for a panel or a health check."""
        return tuple((clone, self.state(clone.bot_id)) for clone in self._store.all())

    def counts(self) -> dict[State, int]:
        return self._states.counts(clone.bot_id for clone in self._store.all())

    def is_running(self, bot_id: int) -> bool:
        return int(bot_id) in self._running

    def running(self) -> tuple[int, ...]:
        return tuple(sorted(self._running))

    def username(self, bot_id: int) -> str:
        entry = self._running.get(int(bot_id))
        return entry[2] if entry else ""

    def profile(self, bot_id: int) -> str:
        """The profile a running clone actually started with."""
        entry = self._running.get(int(bot_id))
        settings = getattr(entry[0], "settings", None) if entry else None
        if settings is None:
            clone = self._store.get(bot_id)
            return "custom" if clone and clone.selected_plugins else profiles.clean(getattr(clone, "profile", None))
        plugins = tuple(getattr(settings, "plugins", ()) or ())
        for name in profiles.ORDER:
            if plugins == tuple(profiles.plugins_for(name, self._settings)):
                return name
        return "custom"

    def record(self, bot_id: int) -> Clone | None:
        """The stored record for a clone, running or not."""
        return self._store.get(bot_id)

    def current(self) -> tuple[Clone, ...]:
        return self._store.all()

    async def start(self, clone: Clone, *, automatic: bool = False) -> str:
        if self._store._db is None:
            return await self._start_assigned(clone, automatic=automatic)
        lock = self._reconciliation_locks.setdefault(clone.bot_id, asyncio.Lock())
        async with lock:
            return await self._reconcile_start(clone, automatic=automatic)

    async def _reconcile_start(self, clone: Clone, *, automatic: bool = False) -> str:
        """All PostgreSQL starts/restarts/recovery use one revision authority."""
        if self._store._db is None:
            return await self._start_assigned(clone, automatic=automatic)
        from .reconcile import CloneReconciler, ReconciliationError
        try:
            await self._store.aall()
            current = self._store.get(clone.bot_id)
            if current is None or (automatic and current.disabled):
                raise ReconciliationError('Clone unavailable')
            state = await self.configuration.read(clone.bot_id)
            revision = state['desired_revision']
            if revision <= 0:
                raise ReconciliationError('Clone requires revision-tracked configuration')
            entry = self._running.get(clone.bot_id)
            live = entry is not None and self._running_revisions.get(clone.bot_id) == revision and getattr(entry[1], "is_connected", True)
            async def apply(configuration):
                if not live:
                    await self.stop(configuration.bot_id)
                    await self._start_assigned(configuration, automatic=automatic, assigned=True)
                lease = getattr(self._running[configuration.bot_id][0], 'lease', None)
                if (lease is None or getattr(lease, 'name', None) != 'agent'
                        or getattr(getattr(lease, '_db', None), 'scope', None) != f'clone:{configuration.bot_id}'):
                    raise ReconciliationError('Worker PostgreSQL lease unavailable')
                return lease
            await CloneReconciler(self.configuration.repository).run(clone.bot_id, revision=revision, apply=apply)
            self._configuration_retry.pop(clone.bot_id, None)
            self._running_revisions[clone.bot_id] = revision
            return self.username(clone.bot_id)
        except asyncio.CancelledError:
            await self.stop(clone.bot_id)
            raise
        except Exception:
            # Failed/lost acknowledgement cannot leave an unconfirmed worker live.
            await self.stop(clone.bot_id)
            self._configuration_retry.setdefault(clone.bot_id, 0)
            raise CloneError('Clone revision reconciliation was not confirmed.') from None

    async def _start_assigned(self, clone: Clone, *, automatic=False, assigned=False) -> str:
        """Start one clone and return its username (``""`` when Telegram hides it)."""
        async with self._lock:
            if self.eligible is not None and not self.eligible(clone.owner_id):
                raise CloneError("Clone owner no longer has premium, sudo or Owner eligibility.")
            if clone.bot_id in self._running:
                return self._running[clone.bot_id][2]
            bot = None
            client = None
            self._states.move(clone.bot_id, State.VALIDATING)
            try:
                bot = self._factory(self.settings_for(clone))
                database = getattr(bot, "database", None)
                if database is not None:
                    if not await database.connect():
                        raise CloneError("Clone PostgreSQL connection is unavailable.")
                    await database.load()
                    if getattr(database, "load_error", None):
                        raise CloneError("Clone PostgreSQL state could not be loaded.")
                    logbook = getattr(bot, "logbook", None)
                    if logbook is not None:
                        await logbook.hydrate()
                    for service in (getattr(bot, "users", None), getattr(bot, "premium", None), getattr(bot, "runtime", None)):
                        if getattr(service, "hydrate", None):
                            service.hydrate()
                lease = getattr(bot, "lease", None)
                if lease is not None and not await lease.acquire(wait_seconds=0):
                    raise CloneError("Another instance owns this clone's lease.")
                if lease is not None:
                    stop_event = asyncio.Event()
                    lease.start_heartbeat(stop_event)
                client = bot.build()
                registry = getattr(bot, "registry", None)
                if registry is not None and clone.selected_plugins:
                    manifests = {manifest.slug: manifest for manifest in registry.manifests()}
                    if any(slug not in manifests or not manifests[slug].commands
                           or not registry.is_enabled(slug) for slug in clone.selected_plugins):
                        raise CloneError("A selected clone plugin is unavailable.")
                self._states.move(clone.bot_id, State.STARTING)
                await client.start()
                if assigned:
                    identity_check = await client.get_me()
                    if getattr(identity_check, 'id', None) != clone.bot_id:
                        raise CloneError('Clone identity confirmation failed.')
                voice = getattr(bot, "voice", None)
                if voice is not None:
                    await voice.start()
                sync_commands = getattr(bot, "_sync_commands", None)
                if sync_commands is not None:
                    await sync_commands(client, reset_button=True)
                if clone.selected_plugins == ("music",) and (voice is None or not voice.connected):
                    raise CloneError("The Music assistant did not connect.")
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - the reason is the message
                category = "UNAUTHORIZED" if "UNAUTHORIZED" in str(exc).upper() else type(exc).__name__
                reason = f"Clone {clone.bot_id} could not start ({category})."
                self._states.move(clone.bot_id, State.FAILED, error=reason)
                logger.warning("clone %s failed to start (%s)", clone.bot_id, type(exc).__name__)
                voice = getattr(bot, "voice", None)
                if voice is not None:
                    try:
                        await voice.shutdown()
                    except Exception:
                        pass
                if client is not None:
                    try:
                        await client.stop()
                    except Exception:
                        pass
                await self._release_worker(bot)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise CloneError(reason) from None
            username = ""
            identity = True
            try:
                me = await client.get_me()
                username = getattr(me, "username", "") or ""
            except Exception:  # noqa: BLE001 - a missing username is cosmetic
                identity = False
                logger.debug("could not read the clone's identity")
            state = self.state(clone.bot_id)
            state.username = username
            if identity:
                state.move(State.RUNNING)
            else:
                # Connected, but we cannot name it: honest degradation instead of
                # a green light we cannot justify.
                state.move(
                    State.DEGRADED,
                    error="connected, but Telegram did not report an identity",
                )
            self._states.set(clone.bot_id, state)
            self._running[clone.bot_id] = (bot, client, username)
            if lease is not None:
                self._lease_monitors[clone.bot_id] = asyncio.create_task(
                    self._watch_lease(clone.bot_id, stop_event), name=f"clone-lease-{clone.bot_id}"
                )
            logger.info("clone %s is running as @%s", clone.bot_id, username or "?")
            return username

    async def stop(self, bot_id: int) -> bool:
        async with self._lock:
            self._configuration_retry.pop(int(bot_id), None)
            self._running_revisions.pop(int(bot_id), None)
            entry = self._running.pop(int(bot_id), None)
            if entry is None:
                return False
            self._states.move(int(bot_id), State.STOPPING)
            bot, client, _username = entry
            monitor = self._lease_monitors.pop(int(bot_id), None)
            if monitor is not None and monitor is not asyncio.current_task():
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            try:
                cleanup = getattr(bot, "_cleanup_services", None)
                if cleanup is not None:
                    await cleanup(client)
                else:
                    await client.stop()
            except Exception:  # noqa: BLE001 - a dead client is still stopped
                logger.warning("clone %s did not stop cleanly", bot_id)
            await self._release_worker(bot)
            self._states.move(int(bot_id), State.STOPPED)
            return True

    async def _watch_lease(self, bot_id, stop_event):
        await stop_event.wait()
        await self.stop(bot_id)

    @staticmethod
    async def _release_worker(bot):
        lease = getattr(bot, "lease", None)
        try:
            if lease is not None:
                try:
                    await lease.stop_heartbeat()
                finally:
                    await lease.release_async()
        finally:
            database = getattr(bot, "database", None)
            if database is not None:
                await database.close()

    async def restart(self, clone: Clone) -> str:
        await self.stop(clone.bot_id)
        return await self.start(clone)

    async def stop_all(self) -> None:
        self._configuration_retry.clear()
        for bot_id in tuple(self._running):
            await self.stop(bot_id)

    async def supervise(self, *, max_attempts: int = 5) -> tuple[int, ...]:
        """One pass: notice dead clients, stop them, start them again if allowed.

        A clone that dropped its connection is *degraded*, not running — the
        previous code kept the entry and reported it up. Retries are capped so a
        revoked token does not turn into a loop.
        """
        restarted: list[int] = []
        try:
            await self._store.aall()
        except Exception:
            await self.stop_all()
            return ()
        for bot_id, attempts in tuple(self._configuration_retry.items()):
            record = self._store.get(bot_id)
            if record is None or record.disabled or attempts >= max_attempts:
                self._configuration_retry.pop(bot_id, None)
                continue
            self._configuration_retry[bot_id] = attempts + 1
            try:
                await self.start(record, automatic=True)
            except CloneError:
                self._configuration_retry[bot_id] = attempts + 1
                continue
        for bot_id in tuple(self._running):
            record = self._store.get(bot_id)
            if record is None or record.disabled:
                await self.stop(bot_id)
                continue
            if record is not None and self.eligible is not None and not self.eligible(record.owner_id):
                await self.stop(bot_id)
                await self._store.aupdate(bot_id, disabled=True)
                continue
            client = self._running[bot_id][1]
            if getattr(client, "is_connected", True):
                if self._store._db is not None:
                    metadata = await self.configuration.read(bot_id)
                    if metadata['desired_revision'] != self._running_revisions.get(bot_id):
                        try:
                            await self.start(record, automatic=True)
                        except CloneError:
                            pass
                continue
            state = self.state(bot_id)
            logger.warning("clone %s dropped its connection", bot_id)
            if state.state is State.RUNNING:
                state.move(State.DEGRADED, error="connection lost")
                self._states.set(bot_id, state)
            await self.stop(bot_id)
            clone = self._store.get(bot_id)
            if clone is None or clone.disabled:
                continue
            if self.state(bot_id).attempts >= max_attempts:
                logger.error(
                    "clone %s has failed %d times; leaving it stopped",
                    bot_id,
                    self.state(bot_id).attempts,
                )
                continue
            try:
                await self.start(clone)
            except CloneError:
                continue
            restarted.append(bot_id)
        if restarted:
            logger.info("supervisor restarted clone(s): %s", restarted)
        return tuple(restarted)

    async def watch(self, interval: float = 15.0, *, max_attempts: int = 5) -> None:
        """Look after the live clients until cancelled."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.supervise(max_attempts=max_attempts)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad pass must not end the loop
                logger.warning("the clone supervisor failed a pass")

    async def restore(self) -> tuple[int, ...]:
        """Start every clone that was running when the process last stopped."""
        started: list[int] = []
        for clone in await self._store.aall():
            if (clone.disabled or self.is_running(clone.bot_id)
                    or (self.eligible is not None and not self.eligible(clone.owner_id))):
                continue
            try:
                await self.start(clone)
            except CloneError as exc:
                logger.warning("could not restore clone %s: %s", clone.bot_id, exc)
                continue
            started.append(clone.bot_id)
        if started:
            logger.info("Restored %d clone(s): %s", len(started), started)
        return tuple(started)


def _default_factory(settings):
    """The real thing: a full bot, built for the clone's own token."""
    from ...bot import AgentBot

    return AgentBot(settings)
