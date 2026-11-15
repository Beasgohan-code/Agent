"""PostgreSQL mode: the same stores, a durable place to put them.

No test here needs a server. What is checked is the contract the stores rely on
— load a document, save a document, hold a lease — with a stand-in database, plus
the decisions this module makes on its own: URL dialects, a missing driver, and
a write queue that never blocks a handler.
"""

import asyncio
import time

import pytest

from agent.modules.clone.store import Clone, CloneStore
from agent.platform.audience import UserIndex
from agent.platform.chats import ChatStore
from agent.platform.db import Database, normalise_url
from agent.platform.instance import InstanceLease
from agent.platform.links import LinkStore, LinkError
from agent.platform.premium import PremiumBook
from agent.platform.runtime import PluginRuntime


class FakeDB:
    """The parts of :class:`Database` the stores touch."""

    def __init__(self, docs=None, *, connected=True):
        self.docs = dict(docs or {})
        self.saved = {}
        self.connected = connected
        self.leases = {}
        self.released = []

    def has(self, name):
        return name in self.docs

    def get(self, name, default=None):
        return self.docs.get(name, default)

    def save(self, name, value):
        self.saved[name] = value
        self.docs[name] = value

    async def take_lease(self, name, holder, ttl):
        current = self.leases.get(name)
        now = time.time()
        if current is None or current[0] == holder or current[1] <= now:
            self.leases[name] = (holder, now + ttl)
            return "taken"
        return "held"

    async def release_lease(self, name, holder):
        if self.leases.get(name, (None,))[0] == holder:
            self.leases.pop(name, None)
            self.released.append(holder)
            return True
        return False

    async def lease_holder(self, name):
        return self.leases.get(name, (None, 0.0))


# --- the URL dialect ------------------------------------------------------


def test_every_postgres_url_dialect_becomes_one_asyncpg_accepts():
    assert normalise_url("postgres://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert (
        normalise_url("postgresql://u:p@h/db?sslmode=require")
        == "postgresql://u:p@h/db"
    )
    assert (
        normalise_url("postgres://u:p@h/db?sslmode=require&channel_binding=require&x=1")
        == "postgresql://u:p@h/db?x=1"
    )
    assert normalise_url("postgresql+asyncpg://u@h/db") == "postgresql://u@h/db"
    assert normalise_url("mysql://u@h/db") is None
    assert normalise_url("") is None


def test_a_database_without_a_url_is_disabled_rather_than_broken():
    database = Database(None)

    assert database.enabled is False
    assert asyncio.run(database.connect()) is False
    database.save("chats", {})  # a no-op, not an exception
    assert asyncio.run(database.flush()) == 0


def test_a_missing_driver_is_reported_not_raised(monkeypatch):
    database = Database("postgresql://u@h/db")
    monkeypatch.setattr(Database, "driver_installed", classmethod(lambda cls: False))

    assert asyncio.run(database.connect()) is False
    assert database.error == "asyncpg is not installed"
    assert database.connected is False


# --- the write queue ------------------------------------------------------


def test_queued_documents_are_written_and_keep_the_latest_value():
    database = Database("postgresql://u@h/db")
    database.connected = True
    written = {}

    async def fake_batch(batch):
        written.update(batch)

    async def main():
        database._write_batch = fake_batch
        database.save("chats", {"a": 1})
        database.save("chats", {"a": 2})
        database.save("premium", {"users": {}})
        return await database.flush()

    assert asyncio.run(main()) == 2
    assert written["chats"] == {"a": 2}  # one row, newest value
    assert written["premium"] == {"users": {}}
    assert database.get("chats") == {"a": 2}


# --- the stores -----------------------------------------------------------


def test_chats_load_from_the_database_and_never_touch_the_file(tmp_path):
    database = FakeDB({"chats": {"-1": {"members": {}, "settings": {"rules": "be kind"}, "log": []}}})

    chats = ChatStore(tmp_path, db=database)
    assert chats.settings(-1)["rules"] == "be kind"

    chats.put(-1, "rules", "new rules")
    assert database.saved["chats"]["-1"]["settings"]["rules"] == "new rules"
    assert not (tmp_path / "chats.json").exists()


def test_premium_ledger_round_trips_through_the_database(tmp_path):
    database = FakeDB({"premium": {"users": {"7": {"until": None}}, "usage": {}}})

    book = PremiumBook(tmp_path, db=database)
    assert book.is_premium(7) is True  # lifetime

    from agent.platform.entitlements import EntitlementError
    with pytest.raises(EntitlementError, match="Awaited"):
        book.grant(8, days=1, by=1)
    assert not database.saved
    assert not (tmp_path / "premium.json").exists()


def test_links_require_awaited_database_operations(tmp_path):
    database = FakeDB()
    links = LinkStore(tmp_path, "secret", db=database)
    with pytest.raises(LinkError, match="Awaited"):
        links.create("file-1", owner_id=7, ttl_hours=1)
    assert not database.saved
    assert not (tmp_path / "links.json").exists()


def test_the_user_index_and_the_plugin_runtime_use_the_database(tmp_path):
    database = FakeDB({"users": {"5": 100.0}, "runtime": {"disabled": ["leech"]}})

    assert UserIndex(tmp_path, db=database).seen(5) is True
    assert UserIndex(tmp_path, db=database).total() == 1

    from agent.platform.manifest import PluginRegistry

    registry = PluginRegistry()
    runtime = PluginRuntime(registry, state_path=tmp_path / "plugins.json", db=database)
    assert runtime.wants_disabled("leech") is True


def test_clone_records_are_shared_through_the_database(tmp_path):
    database = FakeDB({"clones": [{"bot_id": 1, "owner_id": 2, "token": "1:abc"}]})

    store = CloneStore(tmp_path, db=database)
    assert store.get(1).owner_id == 2

    with pytest.raises(RuntimeError, match="Awaited"):
        store.add(Clone(bot_id=3, owner_id=4, token="3:def"))
    assert not database.saved
    assert store.count() == 1


def test_a_store_refuses_file_fallback_when_configured_database_is_down(tmp_path):
    database = FakeDB(connected=False)
    chats = ChatStore(tmp_path, db=database)

    import pytest
    with pytest.raises(RuntimeError, match="refusing local"):
        chats.put(-9, "rules", "not saved")
    assert not (tmp_path / "chats.json").exists()


# --- the lease ------------------------------------------------------------


def test_the_lease_is_taken_in_the_database_and_visible_to_every_instance(tmp_path):
    database = FakeDB()
    first = InstanceLease(tmp_path / "lock", owner="first", beat=0.01, db=database)
    second = InstanceLease(tmp_path / "lock", owner="second", beat=0.01, db=database)

    assert asyncio.run(first.acquire(wait_seconds=0)) is True
    assert asyncio.run(second.acquire(wait_seconds=0)) is False
    assert first.backend == "postgres"

    asyncio.run(first.release_async())
    assert database.released == ["first"]
    assert asyncio.run(second.acquire(wait_seconds=0)) is True


def test_a_stolen_database_lease_stops_the_heartbeat(tmp_path):
    database = FakeDB()
    lease = InstanceLease(tmp_path / "lock", owner="mine", db=database)
    asyncio.run(lease.acquire(wait_seconds=0))
    database.leases["agent"] = ("thief", time.time() + 60)

    assert asyncio.run(lease.beat_once()) is False
    assert lease.held is False


def test_an_unreachable_database_lease_refuses_unprotected_startup(tmp_path):
    class DeadDB(FakeDB):
        async def take_lease(self, *args, **kwargs):
            return "unavailable"

    lease = InstanceLease(tmp_path / "lock", owner="mine", db=DeadDB())

    assert asyncio.run(lease.acquire(wait_seconds=0)) is False
    assert lease.degraded is True
    assert lease.held is False


def test_stores_reread_themselves_once_the_database_has_loaded(tmp_path):
    """They are built during __init__, before the pool is up — this is the fix."""
    from agent.platform.manifest import PluginRegistry

    database = FakeDB({})
    users = UserIndex(tmp_path, db=database)
    book = PremiumBook(tmp_path, db=database)
    runtime = PluginRuntime(PluginRegistry(), state_path=None, db=database)
    assert users.total() == 0 and book.count() == 0

    # What the database turns out to hold, after connect() + load().
    database.docs["users"] = {"5": 1.0}
    database.docs["premium"] = {"users": {"7": {"until": None}}, "usage": {}}
    database.docs["runtime"] = {"disabled": ["leech"]}

    for store in (users, book, runtime):
        store.hydrate()

    assert users.seen(5) is True
    assert book.is_premium(7) is True
    assert runtime.wants_disabled("leech") is True


def test_required_database_never_reads_local_document_fallback(tmp_path):
    from agent.platform.db import Database, load_document
    path = tmp_path / 'old.json'
    path.write_text('{"unsafe": true}')
    db = Database('postgresql://localhost/test', required=True)
    assert load_document(db, 'test', path, {}) == {}
    db.connected = True
    assert load_document(db, 'test', path, {}) == {}


def test_required_database_never_writes_local_fallback(tmp_path):
    import pytest
    from agent.platform.db import Database, save_document
    path = tmp_path / 'state.json'
    db = Database('postgresql://localhost/test', required=True)
    with pytest.raises(RuntimeError, match='refusing local'):
        save_document(db, 'test', path, {'state': 'new'})
    assert not path.exists()


def test_failed_document_load_is_distinguishable_from_empty_database():
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.platform.db import Database
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield SimpleNamespace(fetch=AsyncMock(side_effect=RuntimeError('unavailable')))
    db = Database('postgresql://localhost/test', required=True)
    db.connected = True
    db._pool = Pool()
    assert asyncio.run(db.load()) == 0
    assert db.load_error == 'RuntimeError'


@pytest.mark.parametrize('cancelled', [False, True])
def test_failed_schema_initialization_disposes_pool_and_redacts_errors(monkeypatch, caplog, cancelled):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    async def scenario():
        error = asyncio.CancelledError() if cancelled else RuntimeError('postgresql://private:password@private-host/db')
        connection = SimpleNamespace(execute=AsyncMock(side_effect=error))
        class Acquisition:
            async def __aenter__(self):
                return connection
            async def __aexit__(self, *args):
                pass
        pool = SimpleNamespace(acquire=lambda: Acquisition(), terminate=Mock())
        driver = SimpleNamespace(create_pool=AsyncMock(return_value=pool))
        monkeypatch.setattr(Database, '_driver', staticmethod(lambda: driver))
        db = Database('postgresql://user@host/db')
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await db.connect()
        else:
            assert not await db.connect()
            assert db.error == 'RuntimeError'
        assert db._pool is None and not db.connected
        pool.terminate.assert_called_once()
        assert 'password' not in caplog.text and 'private-host' not in caplog.text
        # Retry creates a fresh, usable pool, never a half-initialized one.
        connection.execute.side_effect = None
        assert await db.connect()
        assert await db.connect()  # Existing connected pool is reused.
        assert driver.create_pool.await_count == 2
        assert db.connected and db._pool is pool
    asyncio.run(scenario())


def test_shutdown_retries_cancelled_inflight_batch_without_overwriting_newer_values(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    async def scenario():
        db = Database('postgresql://user@host/db')
        db.connected = True
        db._pool = SimpleNamespace(close=AsyncMock())
        entered = asyncio.Event()
        attempts = []
        async def write(batch):
            attempts.append(dict(batch))
            if len(attempts) == 1:
                entered.set()
                await asyncio.Event().wait()
        monkeypatch.setattr(db, '_write_batch', write)
        db.save('runtime', {'version': 1})
        db.save('other', {'keep': True})
        await entered.wait()
        db.save('runtime', {'version': 2})
        await db.close()
        assert attempts == [{'runtime': {'version': 1}, 'other': {'keep': True}},
                            {'runtime': {'version': 2}, 'other': {'keep': True}}]
        assert not db._pending
        assert not db.connected and db._pool is None
    asyncio.run(scenario())


def test_concurrent_flushes_commit_in_queue_order(monkeypatch):
    async def scenario():
        db = Database('postgresql://user@host/db')
        db.connected = True
        entered, release = asyncio.Event(), asyncio.Event()
        writes = []
        async def write(batch):
            writes.append(dict(batch))
            if len(writes) == 1:
                entered.set()
                await release.wait()
        monkeypatch.setattr(db, '_write_batch', write)
        db._pending['settings'] = 1
        first = asyncio.create_task(db.flush())
        await entered.wait()
        db._pending['settings'] = 2
        second = asyncio.create_task(db.flush())
        await asyncio.sleep(0)
        assert writes == [{'settings': 1}]
        release.set()
        assert await first == 1 and await second == 1
        assert writes == [{'settings': 1}, {'settings': 2}]
    asyncio.run(scenario())


def test_document_save_snapshots_are_independent_of_caller_and_cache_mutation(monkeypatch):
    async def scenario():
        db = Database('postgresql://user@host/db')
        db.connected = True
        committed = []
        async def write(batch):
            committed.append(batch)
        monkeypatch.setattr(db, '_write_batch', write)
        value = {'group': {'locks': ['url']}}
        db.save('chats', value)
        value['group']['locks'].append('photo')
        assert db.get('chats') == {'group': {'locks': ['url']}}
        db.get('chats')['group']['locks'].append('video')
        assert await db.flush() == 1
        assert committed == [{'chats': {'group': {'locks': ['url']}}}]
        db.save('chats', value)
        await db.flush()
        assert committed[-1] == {'chats': {'group': {'locks': ['url', 'photo']}}}
        if db._writer is not None:
            db._writer.cancel()
            await asyncio.gather(db._writer, return_exceptions=True)
    asyncio.run(scenario())


def test_synchronous_save_retains_snapshot_without_unawaited_coroutine_warning(recwarn):
    import gc
    db = Database('postgresql://user@host/db')
    db.connected = True
    db.save('runtime', {'disabled': ['music']})
    gc.collect()
    assert db._pending == {'runtime': {'disabled': ['music']}}
    assert not any('never awaited' in str(item.message) for item in recwarn)
