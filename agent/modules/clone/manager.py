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
        self._lock = asyncio.Lock()

    # -- settings ---------------------------------------------------------
    def settings_for(self, clone: Clone):
        """The settings a clone runs with: its token, its own directories."""
        return replace(
            self._settings,
            bot_token=clone.token,
            session_name=f"agent_clone_{clone.bot_id}",
            data_dir=self._settings.data_dir / "clones" / str(clone.bot_id),
            # The owner id belongs to the deployment, not to the clone: a clone
            # must not hand owner commands to whoever created it.
            owner_id=None,
        )

    # -- lifecycle --------------------------------------------------------
    def is_running(self, bot_id: int) -> bool:
        return int(bot_id) in self._running

    def running(self) -> tuple[int, ...]:
        return tuple(sorted(self._running))

    def username(self, bot_id: int) -> str:
        entry = self._running.get(int(bot_id))
        return entry[2] if entry else ""

    def current(self) -> tuple[Clone, ...]:
        return self._store.all()

    async def start(self, clone: Clone) -> str:
        """Start one clone and return its username (``""`` when Telegram hides it)."""
        async with self._lock:
            if clone.bot_id in self._running:
                return self._running[clone.bot_id][2]
            bot = self._factory(self.settings_for(clone))
            client = None
            try:
                client = bot.build()
                await client.start()
            except Exception as exc:  # noqa: BLE001 - the reason is the message
                raise CloneError(
                    f"Telegram refused {clone.handle}: {type(exc).__name__}: {exc}"
                ) from exc
            username = ""
            try:
                me = await client.get_me()
                username = getattr(me, "username", "") or ""
            except Exception:  # noqa: BLE001 - a missing username is cosmetic
                logger.debug("could not read the clone's identity", exc_info=True)
            self._running[clone.bot_id] = (bot, client, username)
            logger.info("clone %s is running as @%s", clone.bot_id, username or "?")
            return username

    async def stop(self, bot_id: int) -> bool:
        async with self._lock:
            entry = self._running.pop(int(bot_id), None)
            if entry is None:
                return False
            _bot, client, _username = entry
            try:
                await client.stop()
            except Exception:  # noqa: BLE001 - a dead client is still stopped
                logger.exception("clone %s did not stop cleanly", bot_id)
            return True

    async def restart(self, clone: Clone) -> str:
        await self.stop(clone.bot_id)
        return await self.start(clone)

    async def stop_all(self) -> None:
        for bot_id in tuple(self._running):
            await self.stop(bot_id)

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
