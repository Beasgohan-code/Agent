"""Agent — the owner log channel.

Every notable event is posted to one channel, tagged with a searchable hashtag
(``#NewUser``, ``#NewGroup``, ``#Restart`` …). When no channel is configured the
events go to the owner's DM instead, so an owner who never set one still sees
them. A failed post is logged and dropped; it never breaks a command.
With a configured database the destination is an awaited, tenant-scoped SQL
setting; startup must load it before sending events. Local JSON is standalone
compatibility only, never a fallback for configured PostgreSQL.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from pathlib import Path
from typing import Any, Callable

from .db import read_json, write_json

logger = logging.getLogger(__name__)
MAX_PENDING = 200

#: Event kind → hashtag. Unknown kinds get a CamelCase tag of their own.
TAGS = {
    "start": "BotStarted",
    "stop": "BotStopped",
    "new_user": "NewUser",
    "returning_user": "Start",
    "new_group": "NewGroup",
    "restart": "Restart",
    "plugin": "Plugin",
    "watchdog": "Watchdog",
    "error": "Error",
    "instance": "Instance",
}


def tag_for(kind: str) -> str:
    if kind in TAGS:
        return TAGS[kind]
    return "".join(part.capitalize() for part in kind.replace("-", "_").split("_")) or "Event"


def format_event(kind: str, fields: dict[str, Any], *, when: float | None = None) -> str:
    """Render one event as HTML for the log channel."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(when or time.time()))
    lines = [f"<b>#{tag_for(kind)}</b>", f"<i>{stamp}</i>"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        lines.append(f"{html.escape(str(key))}: <code>{html.escape(str(value))}</code>")
    return "\n".join(lines)


class LogSettingsError(RuntimeError):
    """The destination was not confirmed durable; keep the previous setting."""


class LogBook:
    """Posts events to the log channel, or to the owner when there is none."""

    def __init__(
        self,
        root: Path,
        *,
        channel_id: int | None = None,
        owner_id: int | None = None,
        db=None,
    ) -> None:
        self._path = Path(root) / "logbook.json"
        self._db = db
        self._default_channel = channel_id
        self._config_loaded = db is None
        self._settings_lock = asyncio.Lock()
        self._channel_id = channel_id
        self.owner_id = owner_id
        self.client = None
        self._pending: set[asyncio.Task] = set()
        self._closing = False
        self.dropped = 0
        if db is None:
            self._apply(read_json(self._path, {}))

    # -- configuration -----------------------------------------------------

    def _apply(self, stored):
        self._channel_id = self._default_channel
        if isinstance(stored, dict) and "channel_id" in stored:
            value = stored["channel_id"]
            if value is None or (isinstance(value, int) and not isinstance(value, bool) and value < 0):
                self._channel_id = value

    @property
    def backend(self):
        return "postgres" if self._db is not None else "local file (standalone)"

    async def hydrate(self):
        """Load authoritative bot-scoped settings before Telegram event delivery.

        Configured database mode never falls back to an ephemeral JSON setting.
        An explicit NULL overrides LOG_CHANNEL; an absent row uses the env default.
        """
        async with self._settings_lock:
            if self._db is None:
                self._apply(read_json(self._path, {}))
                self._config_loaded = True
                return
            self._config_loaded = False
            db = self._db
            if not db.connected or db._pool is None:
                raise LogSettingsError("PostgreSQL log settings are unavailable.")
            try:
                async with db._pool.acquire(timeout=10) as connection:
                    row = await connection.fetchrow(
                        'SELECT channel_id FROM agent_log_settings WHERE tenant=$1', db.scope, timeout=10)
            except Exception:
                raise LogSettingsError("Could not read PostgreSQL log settings.") from None
            self._apply({"channel_id": row['channel_id']} if row is not None else {})
            self._config_loaded = True

    @staticmethod
    def _validate(channel_id):
        if channel_id is not None and (not isinstance(channel_id, int) or isinstance(channel_id, bool)
                                       or not -(2**63) < channel_id < 0):
            raise LogSettingsError("Use a negative Telegram channel or group id.")

    async def configure(self, channel_id):
        """Acknowledge only after the database commit (or standalone atomic write)."""
        self._validate(channel_id)
        async with self._settings_lock:
            if self._db is None:
                try:
                    write_json(self._path, {"channel_id": channel_id})
                except (OSError, ValueError):
                    raise LogSettingsError("Could not save the standalone log setting.") from None
            else:
                db = self._db
                if not db.connected or db._pool is None:
                    raise LogSettingsError("PostgreSQL is unavailable; the log setting was not changed.")
                try:
                    async with db._pool.acquire(timeout=10) as connection:
                        await connection.execute('''INSERT INTO agent_log_settings (tenant,channel_id)
                            VALUES ($1,$2) ON CONFLICT (tenant) DO UPDATE
                            SET channel_id=EXCLUDED.channel_id,updated_at=now()''', db.scope, channel_id, timeout=10)
                except (Exception, asyncio.CancelledError) as exc:
                    self._config_loaded = False  # commit outcome may be ambiguous; do not route to stale state
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise LogSettingsError("PostgreSQL did not confirm the log setting. Check /log before retrying.") from None
            self._channel_id = channel_id
            self._config_loaded = True

    @property
    def channel_id(self) -> int | None:
        return self._channel_id

    def destination(self) -> int | None:
        """Where events go: the channel, else the owner, else nowhere yet."""
        return self._channel_id if self._channel_id is not None else self.owner_id

    def set_channel(self, channel_id: int | None) -> None:
        if self._db is not None:
            raise LogSettingsError("Use awaited configure() for PostgreSQL settings.")
        self._validate(channel_id)
        write_json(self._path, {"channel_id": channel_id})
        self._channel_id = channel_id

    # -- delivery ----------------------------------------------------------

    async def post(self, kind: str, **fields: Any) -> bool:
        """Send one event. False when there is nowhere (or no client) to send it."""
        target = self.destination()
        if not self._config_loaded:
            logger.warning("Log destination has not been loaded; event delivery is suppressed.")
            return False
        if self.client is None or target is None:
            logger.info("#%s %s (no log destination)", tag_for(kind), fields)
            return False
        text = format_event(kind, fields)
        try:
            await asyncio.wait_for(
                self.client.send_message(target, text, disable_web_page_preview=True),
                timeout=10.0,
            )
            return True
        except Exception:  # noqa: BLE001 - logging must never break the bot
            logger.exception("Could not post #%s to the log channel", tag_for(kind))
            return False

    def publish(self, kind: str, fields: dict[str, Any]) -> None:
        """Fire-and-forget from a synchronous context (the event log)."""
        if self._closing:
            return
        if len(self._pending) >= MAX_PENDING:
            self.dropped += 1
            if self.dropped == 1:
                logger.warning("Log-channel queue is full; dropping excess best-effort posts.")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop outside a running bot
            return
        task = loop.create_task(self.post(kind, **fields))
        # Keep a reference so the task is not garbage-collected mid-flight.
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def close(self, *, timeout: float = 5.0) -> None:
        """Stop accepting events and drain this bot's posts before disconnect."""
        self._closing = True
        pending = tuple(self._pending)
        try:
            if pending:
                try:
                    _, unfinished = await asyncio.wait(pending, timeout=max(0.0, timeout))
                except asyncio.CancelledError:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    raise
                for task in unfinished:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        finally:
            self.client = None


def subscribe(event_log, logbook: LogBook) -> Callable[[], None]:
    """Bridge an :class:`EventLog` to the channel. Returns an unsubscribe."""
    def listener(kind: str, fields: dict[str, Any]) -> None:
        logbook.publish(kind, fields)

    event_log.subscribe(listener)
    return lambda: event_log.unsubscribe(listener)
