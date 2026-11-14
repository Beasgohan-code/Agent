"""Agent — PostgreSQL, when ``DATABASE_URL`` is set.

The bot worked from JSON files for a good reason: one process, one small state.
A deployment with several instances (the main bot, its clones, a rolling deploy
that briefly runs two copies) breaks that assumption, so there is a database
mode with the same behaviour and a different place to keep it.

Two tables, nothing more:

* ``agent_documents`` — one row per store (``chats``, ``premium``, ``links``,
  ``clones``, ``runtime``, ``users``), the whole document as ``jsonb``. The
  stores keep their in-memory form; this is where it is made durable.
* ``agent_lease`` — the single-instance lease, as a row that only one holder can
  own, so "two processes, one token" is decided by the database rather than by a
  file that two containers cannot see.

Why documents and not one table per feature: every store already reads and
writes a JSON document, and a schema with fifteen normalised tables would need a
migration for each new setting. ``jsonb`` keeps the store code as it is and puts
the durability where it belongs.

Writes are batched: a mutation queues the document and one background task
flushes the queue, so a handler never waits on the network. A database that is
missing or unreachable is logged once and the bot keeps running on its files —
losing the database must not take the bot down with it.

**Every row is scoped to one bot.** The main bot and each clone connect to the
same database, and they all keep a document called ``runtime``, ``premium`` or
``chats`` — unscoped, the last writer would silently win and a clone's plugin
switch could turn off the main bot's. So a :class:`Database` is constructed with
a *scope* (``main:<bot id>`` or ``clone:<bot id>``) and every document name and
lease name is stored as ``<scope>:<name>``. The stores keep using plain names;
the prefix exists only in the SQL. ``scope="global"`` is there for data that is
genuinely deployment-wide.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .plugin_access import SCHEMA as PLUGIN_SCHEMA

logger = logging.getLogger(__name__)

#: Everything this module needs, in one statement each. Safe to run every boot.
SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS agent_documents (
        name TEXT PRIMARY KEY,
        value JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_lease (
        name TEXT PRIMARY KEY,
        holder TEXT NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
)

SCHEMA += PLUGIN_SCHEMA

UPSERT_DOCUMENT = """
    INSERT INTO agent_documents (name, value)
    VALUES ($1, $2::jsonb)
    ON CONFLICT (name) DO UPDATE
    SET value = EXCLUDED.value, updated_at = NOW()
"""

TAKE_LEASE = """
    INSERT INTO agent_lease (name, holder, expires_at)
    VALUES ($1, $2, $3)
    ON CONFLICT (name) DO UPDATE
    SET holder = EXCLUDED.holder, expires_at = EXCLUDED.expires_at, updated_at = NOW()
    WHERE agent_lease.holder = EXCLUDED.holder
       OR agent_lease.expires_at <= $4
    RETURNING holder
"""

RELEASE_LEASE = "DELETE FROM agent_lease WHERE name = $1 AND holder = $2"

READ_LEASE = "SELECT holder, expires_at FROM agent_lease WHERE name = $1"


def normalise_url(raw: str | None) -> str | None:
    """Postgres URLs arrive in three dialects; asyncpg wants ``postgres://`` gone.

    Heroku and Render hand out ``postgres://``; asyncpg refuses that scheme, and
    several providers append ``?sslmode=require``, which asyncpg does not
    understand as a DSN parameter. Both are fixed here, once.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://") :]
    if text.startswith("postgresql+asyncpg://"):
        text = "postgresql://" + text[len("postgresql+asyncpg://") :]
    if not text.startswith("postgresql://"):
        logger.warning("DATABASE_URL is not a PostgreSQL URL; ignoring it")
        return None
    # asyncpg has no sslmode; the parameter is honoured by demanding TLS instead.
    if "sslmode=" in text:
        base, _, query = text.partition("?")
        keep = [
            part
            for part in query.split("&")
            if part and not part.startswith(("sslmode=", "channel_binding="))
        ]
        text = base + (("?" + "&".join(keep)) if keep else "")
    return text


class Database:
    """The connection, the document cache and the write-behind queue."""

    def __init__(
        self,
        url: str | None,
        *,
        scope: str = "global",
        required: bool = False,
        flush_interval: float = 0.05,
    ) -> None:
        self.url = normalise_url(url)
        #: Which bot owns these rows: ``main:<id>``, ``clone:<id>``, ``global``.
        self.scope = _clean_scope(scope)
        self.connected = False
        self.required = required
        self.load_error: str | None = None
        self.error: str | None = None
        self._pool = None
        self._docs: dict[str, Any] = {}
        self._pending: dict[str, Any] = {}
        self._writer: asyncio.Task | None = None
        self._warned = False
        self._flush_interval = flush_interval

    # -- scoping -----------------------------------------------------------
    def name_for(self, name: str) -> str:
        """The stored name of *name*: the scope prefix is the whole trick."""
        return f"{self.scope}:{name}"

    def lease_key(self, name: str) -> str:
        """A lease is per scope too: two bots of one deployment never contend."""
        return f"{self.scope}:{name}"

    def _pattern(self) -> str:
        """``LIKE`` pattern matching only this scope's rows."""
        escaped = (
            self.scope.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return f"{escaped}:%"

    # -- capability --------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self.url is not None

    @staticmethod
    def _driver():
        """The asyncpg module, or ``None`` when the wheel is not installed."""
        try:
            import asyncpg
        except ImportError:
            return None
        return asyncpg

    @classmethod
    def driver_installed(cls) -> bool:
        return cls._driver() is not None

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> bool:
        """Connect and apply the schema. False means "stay on the files"."""
        if self.url is None:
            return False
        if not self.driver_installed():
            self.error = "asyncpg is not installed"
            logger.warning(
                "DATABASE_URL is set but asyncpg is not installed; using JSON files. "
                "Install it with `pip install asyncpg`."
            )
            return False
        try:
            asyncpg = self._driver()
            self._pool = await asyncpg.create_pool(
                dsn=self.url, min_size=1, max_size=4, command_timeout=10
            )
            async with self._pool.acquire() as connection:
                for statement in SCHEMA:
                    await connection.execute(statement)
        except Exception as exc:  # noqa: BLE001 - a database is an option, not a requirement
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Could not use PostgreSQL (%s); falling back to JSON files.", self.error
            )
            self._pool = None
            self.connected = False
            return False
        self.connected = True
        self.error = None
        logger.info("PostgreSQL connected; stores are backed by agent_documents")
        return True

    async def load(self) -> int:
        """Read every stored document into memory. Returns how many were found."""
        self.load_error = None
        if not self.connected or self._pool is None:
            self.load_error = "PostgreSQL is not connected"
            return 0
        try:
            async with self._pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT name, value FROM agent_documents WHERE name LIKE $1",
                    self._pattern(),
                )
        except Exception as exc:  # noqa: BLE001
            self.load_error = type(exc).__name__
            logger.warning("Could not read documents from PostgreSQL: %s", type(exc).__name__)
            return 0
        self._docs = {}
        prefix = f"{self.scope}:"
        for row in rows:
            # Only this scope's rows were asked for, but strip the prefix anyway
            # so the stores keep seeing the plain names they have always used.
            name = str(row["name"])
            if not name.startswith(prefix):
                continue
            self._docs[name[len(prefix) :]] = _decode(row["value"])
        if self._docs:
            logger.info("Loaded %d document(s) from PostgreSQL", len(self._docs))
        return len(self._docs)

    async def close(self) -> None:
        await self.flush()
        if self._writer is not None and not self._writer.done():
            self._writer.cancel()
            try:
                await self._writer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        self.connected = False

    # -- documents ---------------------------------------------------------
    def get(self, name: str, default: Any = None) -> Any:
        return self._docs.get(name, default)

    def has(self, name: str) -> bool:
        return name in self._docs

    def save(self, name: str, value: Any) -> None:
        """Queue a document write. Never blocks, never raises at a handler."""
        if not self.connected:
            return
        self._docs[name] = value
        self._pending[name] = value
        if self._writer is not None and not self._writer.done():
            return
        try:
            self._writer = asyncio.create_task(self._drain(), name="agent-db-writer")
        except RuntimeError:
            # No event loop (a synchronous test, or shutdown): the pending
            # document stays queued and the next flush picks it up.
            logger.debug("no running loop to flush %r yet", name)

    async def _drain(self) -> None:
        while self._pending:
            batch = dict(self._pending)
            self._pending.clear()
            try:
                await self._write_batch(batch)
            except Exception as exc:  # noqa: BLE001 - durability is best effort
                if not self._warned:
                    logger.warning("Could not persist documents: %s", exc)
                    self._warned = True
                # Put them back so a later flush retries, without looping hot.
                for key, value in batch.items():
                    self._pending.setdefault(key, value)
                await asyncio.sleep(1.0)
                return
            await asyncio.sleep(self._flush_interval)

    async def _write_batch(self, batch: dict[str, Any]) -> None:
        if self._pool is None:
            raise RuntimeError("not connected")
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                for name, value in batch.items():
                    await connection.execute(
                        UPSERT_DOCUMENT, self.name_for(name), json.dumps(value)
                    )

    async def flush(self) -> int:
        """Write everything queued right now. Returns how many documents went."""
        if not self.connected or not self._pending:
            return 0
        batch = dict(self._pending)
        self._pending.clear()
        try:
            await self._write_batch(batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Final flush failed: %s", exc)
            for key, value in batch.items():
                self._pending.setdefault(key, value)
            return 0
        return len(batch)

    # -- the lease ---------------------------------------------------------
    async def take_lease(self, name: str, holder: str, ttl: float) -> str:
        """``"held"``, ``"taken"``, ``"renewed"`` or ``"unavailable"``."""
        if not self.connected or self._pool is None:
            return "unavailable"
        now = time.time()
        try:
            async with self._pool.acquire() as connection:
                row = await connection.fetchrow(
                    TAKE_LEASE, self.lease_key(name), holder, now + ttl, now
                )
                if row is None:
                    other = await connection.fetchrow(READ_LEASE, self.lease_key(name))
                    # A concurrent release is not proof that this caller acquired
                    # the row. Retry rather than claiming nonexistent ownership.
                    return "held" if other else "unavailable"
                current = await connection.fetchrow(READ_LEASE, self.lease_key(name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lease query failed: %s", exc)
            return "unavailable"
        if current is None or current["holder"] != holder:
            return "held"
        return "taken" if (current["expires_at"] or 0) <= now + 0.001 else "renewed"

    async def release_lease(self, name: str, holder: str) -> bool:
        if not self.connected or self._pool is None:
            return False
        try:
            async with self._pool.acquire() as connection:
                result = await connection.execute(
                    RELEASE_LEASE, self.lease_key(name), holder
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not release the lease: %s", exc)
            return False
        return result.endswith(" 1")

    async def lease_holder(self, name: str) -> tuple[str | None, float]:
        if not self.connected or self._pool is None:
            return None, 0.0
        try:
            async with self._pool.acquire() as connection:
                row = await connection.fetchrow(READ_LEASE, self.lease_key(name))
        except Exception:  # noqa: BLE001
            return None, 0.0
        if row is None:
            return None, 0.0
        return row["holder"], float(row["expires_at"] or 0.0)


def _clean_scope(scope: str) -> str:
    """A scope is a name: letters, digits, dash, underscore and one colon."""
    text = "".join(
        char for char in str(scope or "").strip() if char.isalnum() or char in "-_:"
    )
    return text[:80] or "global"


def _decode(value: Any) -> Any:
    """asyncpg returns ``jsonb`` as a string unless a codec is installed."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


# -- the file/database bridge used by the stores ---------------------------


def load_document(database: Database | None, name: str, path: Path, default: Any) -> Any:
    """The document for *name*: from PostgreSQL when it has one, else the file."""
    if database is not None and database.connected and database.has(name):
        value = database.get(name)
        if value is not None:
            return value
    if database is not None and getattr(database, "required", False):
        return default
    return read_json(path, default)


def save_document(database: Database | None, name: str, path: Path, value: Any) -> None:
    """Persist *value*: to PostgreSQL when it is connected, else to the file."""
    if database is not None and database.connected:
        database.save(name, value)
        return
    if database is not None and getattr(database, "required", False):
        raise RuntimeError("PostgreSQL required: refusing local document write")
    write_json(path, value)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("%s is unreadable; starting from the default", path.name)
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    tmp.replace(path)
