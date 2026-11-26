"""Warning authority survives independent controllers and stale document flushes."""
import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.platform.chats import ChatStore
from agent.platform.db import Database


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')
def test_warning_concurrency_restart_isolation_and_legacy(tmp_path):
    async def scenario():
        scope = 'warnings:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=s) for s in (scope, scope, scope + ':other')]
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            # Real persisted legacy history is imported once, not from a cache.
            legacy = {'-100': {'members': {'7': {'warnings': [
                {'reason': 'legacy', 'by': 1, 'at': 1, 'active': True}]}}, 'settings': {}, 'log': []}}
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)', dbs[0].name_for('chats'), json.dumps(legacy))
            stores = [ChatStore(tmp_path / str(i), db=db) for i, db in enumerate(dbs)]
            counts = await asyncio.gather(*(stores[i % 2].aadd_warning(-100, 7, moderator_id=i + 1, reason=str(i)) for i in range(20)))
            assert sorted(counts) == list(range(2, 22))
            # A stale whole-document writer must not erase canonical warnings.
            stores[1].put(-100, 'unrelated', 'stale writer')
            await dbs[1].flush()
            replacement = ChatStore(tmp_path / 'replacement', db=dbs[1])
            assert len(await replacement.awarnings_of(-100, 7)) == 21
            assert await stores[2].awarnings_of(-100, 7) == []
            assert await stores[0].awarnings_of(-101, 7) == []
            assert await stores[0].awarnings_of(-100, 8) == []
            cleared = await asyncio.gather(*(stores[i % 2].aclear_warning(-100, 7) for i in range(25)))
            assert sum(cleared) == 21
            assert not await replacement.awarnings_of(-100, 7)
            await stores[0].aadd_warning(-100, 7, moderator_id=1, reason='new')
            assert await stores[1].aclear_all_warnings(-100, 7) == 1
            assert await replacement.aclear_all_warnings(-100, 7) == 0
        finally:
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_database_warning_sync_mutations_fail_before_cache_change(tmp_path):
    store = ChatStore(tmp_path, db=SimpleNamespace(connected=False))
    for method, args, kwargs in (
        ('add_warning', (-100, 7), {'moderator_id': 1, 'reason': 'x'}),
        ('clear_warning', (-100, 7), {}),
        ('clear_all_warnings', (-100, 7), {}),
    ):
        with pytest.raises(RuntimeError, match='Awaited'):
            getattr(store, method)(*args, **kwargs)
    assert store._chats == {}


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')
def test_warning_rollback_unavailability_bounds_and_validation(tmp_path):
    from agent.platform.warnings import WarningStoreError

    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='warnings:' + uuid.uuid4().hex)
        function = 'fail_warnings_' + uuid.uuid4().hex
        try:
            assert await db.connect()
            await db.load()
            store = ChatStore(tmp_path, db=db, max_warnings=3)
            for i in range(5):
                assert await store.aadd_warning(-100, 7, moderator_id=0, reason='x' * 600) == min(i + 1, 3)
            rows = await store.awarnings_of(-100, 7)
            assert len(rows) == 3 and all(len(row['reason']) == 500 for row in rows)
            rows[0]['active'] = False
            assert len(await store.awarnings_of(-100, 7)) == 3
            assert not store._chats  # Canonical state must never be queued as chats JSON.
            async with db._pool.acquire() as conn:
                await conn.execute(f'''CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN IF NEW.tenant = '{db.scope}' THEN
                    RAISE EXCEPTION 'synthetic-private-db-error'; END IF; RETURN NEW; END $$''')
                await conn.execute(f'CREATE TRIGGER {function} BEFORE UPDATE ON agent_member_warnings FOR EACH ROW EXECUTE FUNCTION {function}()')
            with pytest.raises(WarningStoreError) as error:
                await store.aclear_all_warnings(-100, 7)
            assert 'synthetic-private' not in str(error.value)
            assert not store._chats and not db._pending
            async with db._pool.acquire() as conn:
                await conn.execute(f'DROP TRIGGER {function} ON agent_member_warnings')
            assert len(await store.awarnings_of(-100, 7)) == 3
            for chat, user, actor in ((100, 7, 1), (-100, 0, 1), (-100, 7, -1), (-100, True, 1)):
                with pytest.raises(WarningStoreError):
                    await store.aadd_warning(chat, user, moderator_id=actor, reason='invalid')
            db.connected = False
            with pytest.raises(WarningStoreError, match='unavailable'):
                await store.aadd_warning(-100, 7, moderator_id=1, reason='offline')
            assert not (tmp_path / 'chats.json').exists()
            db.connected = True
            assert len(await store.awarnings_of(-100, 7)) == 3
        finally:
            db.connected = True
            if db._pool:
                async with db._pool.acquire() as conn:
                    await conn.execute(f'DROP TRIGGER IF EXISTS {function} ON agent_member_warnings')
                    await conn.execute(f'DROP FUNCTION IF EXISTS {function}()')
            await db.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')
def test_warning_handler_persistence_denial_and_cancelled_mutation(tmp_path):
    from agent.config import Settings
    from agent.modules import moderation
    from agent.platform.context import ModuleContext
    from agent.ui.theme import Theme
    from test_moderation import ENV, FakeClient, FakeMessage, MEMBER

    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='warnings:' + uuid.uuid4().hex)
        try:
            assert await db.connect()
            await db.load()
            ctx = ModuleContext(settings=Settings.from_env(ENV), theme=Theme(),
                                sender=None, jobs=None, storage=None, links=None,
                                chats=ChatStore(tmp_path, db=db), db=db)
            handlers = moderation.build(ctx)[1]
            denied = FakeMessage('/warn 22 no')
            await handlers['warn'](FakeClient(caller=MEMBER), denied)
            assert not await ctx.chats.awarnings_of(denied.chat.id, 22)
            message = FakeMessage('/warn 22 reason')
            await handlers['warn'](FakeClient(), message)
            assert 'Warning issued' in message.replies[0]
            await db.flush()  # Includes the separate, legacy moderation log.
            restored = ChatStore(tmp_path / 'restored', db=db)
            assert await restored.aactive_warning_count(message.chat.id, 22) == 1
            # Cancel while waiting for a real PostgreSQL lock, not a mocked pool.
            async with db._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                       db.name_for(f'warnings:{message.chat.id}:22'))
                    task = asyncio.create_task(restored.aclear_warning(message.chat.id, 22))
                    # Wait for this pool's blocked transaction to be visible.
                    for _ in range(100):
                        blocked = await conn.fetchval("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted")
                        if blocked:
                            break
                        await asyncio.sleep(0.01)
                    assert blocked
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            assert await restored.aactive_warning_count(message.chat.id, 22) == 1
            message = FakeMessage('/unwarn 22')
            await handlers['unwarn'](FakeClient(), message)
            assert 'Warning cleared' in message.replies[0]
            assert not await restored.awarnings_of(message.chat.id, 22)
        finally:
            await db.close()
    asyncio.run(scenario())
