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
from dataclasses import replace
from typing import Callable

from . import lifecycle, profiles
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
        #: bot_id -> (bot, client, username)
        self._running: dict[int, tuple[object, object, str]] = {}
        #: What each worker is doing, including the ones that are not running.
        self._states = lifecycle.Registry()
        self._lock = asyncio.Lock()

    # -- settings ---------------------------------------------------------
    def settings_for(self, clone: Clone):
        """The settings a clone runs with: its token, directories and profile.

        The profile is what makes a clone small: ``files`` registers the file
        machinery and nothing else, so a pasted token cannot reach moderation,
        music or this deployment's controls.
        """
        return replace(
            self._settings,
            bot_token=clone.token,
            session_name=f"agent_clone_{clone.bot_id}",
            data_dir=self._settings.data_dir / "clones" / str(clone.bot_id),
            # The owner id belongs to the deployment, not to the clone: a clone
            # must not hand owner commands to whoever created it.
            owner_id=None,
            # Its own rows in PostgreSQL. Without this every clone would write
            # the same ``runtime``/``premium``/``chats`` documents as the main
            # bot and the last writer would silently win.
            db_scope=f"clone:{clone.bot_id}",
            plugins=profiles.plugins_for(clone.profile, self._settings),
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
            return profiles.clean(getattr(clone, "profile", None))
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

    async def start(self, clone: Clone) -> str:
        """Start one clone and return its username (``""`` when Telegram hides it)."""
        async with self._lock:
            if clone.bot_id in self._running:
                return self._running[clone.bot_id][2]
            bot = self._factory(self.settings_for(clone))
            client = None
            self._states.move(clone.bot_id, State.VALIDATING)
            try:
                client = bot.build()
                self._states.move(clone.bot_id, State.STARTING)
                await client.start()
            except Exception as exc:  # noqa: BLE001 - the reason is the message
                reason = f"Telegram refused {clone.handle}: {type(exc).__name__}: {exc}"
                self._states.move(clone.bot_id, State.FAILED, error=str(exc))
                logger.warning("clone %s failed to start: %s", clone.bot_id, exc)
                raise CloneError(reason) from exc
            username = ""
            identity = True
            try:
                me = await client.get_me()
                username = getattr(me, "username", "") or ""
            except Exception:  # noqa: BLE001 - a missing username is cosmetic
                identity = False
                logger.debug("could not read the clone's identity", exc_info=True)
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
            logger.info("clone %s is running as @%s", clone.bot_id, username or "?")
            return username

    async def stop(self, bot_id: int) -> bool:
        async with self._lock:
            entry = self._running.pop(int(bot_id), None)
            if entry is None:
                return False
            self._states.move(int(bot_id), State.STOPPING)
            _bot, client, _username = entry
            try:
                await client.stop()
            except Exception:  # noqa: BLE001 - a dead client is still stopped
                logger.exception("clone %s did not stop cleanly", bot_id)
            self._states.move(int(bot_id), State.STOPPED)
            return True

    async def restart(self, clone: Clone) -> str:
        await self.stop(clone.bot_id)
        return await self.start(clone)

    async def stop_all(self) -> None:
        for bot_id in tuple(self._running):
            await self.stop(bot_id)

    async def supervise(self, *, max_attempts: int = 5) -> tuple[int, ...]:
        """One pass: notice dead clients, stop them, start them again if allowed.

        A clone that dropped its connection is *degraded*, not running — the
        previous code kept the entry and reported it up. Retries are capped so a
        revoked token does not turn into a loop.
        """
        restarted: list[int] = []
        for bot_id in tuple(self._running):
            client = self._running[bot_id][1]
            if getattr(client, "is_connected", True):
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
                logger.exception("the clone supervisor failed a pass")

    async def restore(self) -> tuple[int, ...]:
        """Start every clone that was running when the process last stopped."""
        started: list[int] = []
        for clone in self._store.all():
            if clone.disabled or self.is_running(clone.bot_id):
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
