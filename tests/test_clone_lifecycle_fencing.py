"""Lifecycle races use independent PostgreSQL pools, not cached authority."""
import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.modules.clone.manager import CloneManager
from agent.modules.clone.reconcile import CloneReconciler, ReconciliationError
from agent.modules.clone.store import Clone, CloneStore
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, MEMBER, TOKEN_A

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')


@pytest.mark.parametrize('recovery', [False, True])
@pytest.mark.parametrize('action', ['disable', 'disable_enable', 'delete', 'recreate'])
def test_lifecycle_change_fences_old_application(tmp_path, action, recovery):
    async def scenario():
        scope = 'lifecycle-fence:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        for db in dbs:
            assert await db.connect()
        ctx, _, _ = build(tmp_path / 'ctx')
        stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
        managers = [CloneManager(ctx.settings, store) for store in stores]
        repo = managers[0].configuration.repository
        bot_id = 111111111
        entered, release = asyncio.Event(), asyncio.Event()
        async def apply(config):
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute('''INSERT INTO agent_lease(name,holder,expires_at)
                    VALUES($1,'worker',EXTRACT(EPOCH FROM clock_timestamp())+60)
                    ON CONFLICT(name) DO UPDATE SET holder=EXCLUDED.holder,expires_at=EXCLUDED.expires_at''',
                    CloneReconciler.worker_key(bot_id))
            return SimpleNamespace(owner='worker')
        task = None
        try:
            original = await stores[0].aadd(Clone(bot_id=bot_id, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            if recovery:
                await CloneReconciler(repo).run(bot_id, revision=1, apply=apply)
            before = await repo.read(bot_id)
            async def blocked(config):
                worker = await apply(config)
                entered.set()
                await release.wait()
                return worker
            task = asyncio.create_task(CloneReconciler(repo).run(bot_id, revision=1, apply=blocked))
            await asyncio.wait_for(entered.wait(), 5)
            if action in ('disable', 'disable_enable'):
                await stores[1].aupdate(bot_id, disabled=True)
                if action == 'disable_enable':
                    await stores[1].aupdate(bot_id, disabled=False)
            else:
                await stores[1].aremove(bot_id)
                if action == 'recreate':
                    recreated = await stores[1].aadd(Clone(bot_id=bot_id, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
                    assert recreated.configuration_revision == 2
            release.set()
            with pytest.raises(ReconciliationError):
                await task
            state = await repo.read(bot_id)
            assert state['applied_revision'] == before['applied_revision']
            if action == 'recreate':
                assert state['pending_revision'] == state['desired_revision'] == 2
                assert recreated.lifecycle_generation > original.lifecycle_generation
            elif action == 'disable_enable':
                assert stores[1].get(bot_id).lifecycle_generation > original.lifecycle_generation
                await CloneReconciler(repo).run(bot_id, revision=1, apply=apply)
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT string_agg(value::text,\' \') FROM agent_documents WHERE name LIKE $1', scope + ':%')
            assert TOKEN_A not in raw
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
                await conn.execute('DELETE FROM agent_lease WHERE name=$1', CloneReconciler.worker_key(bot_id))
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_disabled_clone_is_rejected_before_application(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='lifecycle-disabled:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            await store.aadd(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            await store.aupdate(111111111, disabled=True)
            calls = []
            async def apply(config):
                calls.append(config.bot_id)
                return SimpleNamespace(owner='not-owned')
            with pytest.raises(ReconciliationError):
                await CloneReconciler(manager.configuration.repository).run(111111111, revision=1, apply=apply)
            assert not calls
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', db.scope + ':%')
            await db.close()
    asyncio.run(scenario())


def test_remote_stop_fences_startup_and_explicit_start_reenables(tmp_path):
    async def scenario():
        from agent.modules.clone.manager import CloneError
        from agent.platform.instance import InstanceLease
        from test_clone import FakeBot
        scope = 'lifecycle-manager:' + uuid.uuid4().hex
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        dbs = [Database(uri, scope=scope) for _ in range(2)]
        for db in dbs:
            assert await db.connect()
        ctx, _, _ = build(tmp_path / 'ctx')
        entered, release = asyncio.Event(), asyncio.Event()
        workers = []
        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.database = Database(uri, scope=settings.db_scope)
                self.lease = InstanceLease(tmp_path / 'unused', db=self.database)
                workers.append(self)
            async def _sync_commands(self, client, **kwargs):
                entered.set()
                await release.wait()
        stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
        managers = [CloneManager(ctx.settings, store, factory=Worker) for store in stores]
        task = None
        try:
            clone = await stores[0].aadd(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            task = asyncio.create_task(managers[0].start(clone))
            await asyncio.wait_for(entered.wait(), 5)
            # The second controller owns no local worker. Its stop must still
            # persist intent before the first controller can acknowledge.
            assert await managers[1].stop(clone.bot_id)
            release.set()
            with pytest.raises(CloneError):
                await task
            assert not managers[0].is_running(clone.bot_id)
            assert (await managers[0].configuration.read(clone.bot_id))['applied_revision'] == 0
            await stores[0].aall()
            stopped_generation = stores[0].get(clone.bot_id).lifecycle_generation
            assert stores[0].get(clone.bot_id).disabled is True
            await managers[0].supervise()
            assert len(workers) == 1  # recovery must not override explicit stop
            await managers[0].start(clone)
            assert stores[0].get(clone.bot_id).disabled is False
            assert stores[0].get(clone.bot_id).lifecycle_generation > stopped_generation
            n = len(workers)
            await managers[0].restart(clone)
            assert len(workers) == n + 1
            await managers[1].stop(clone.bot_id)
            await managers[0].supervise()
            assert not managers[0].is_running(clone.bot_id)
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            for manager in managers:
                await manager.stop_all()
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_generation_cas_rollback_and_tenant_isolation(tmp_path):
    async def scenario():
        import json
        scope = 'lifecycle-cas:' + uuid.uuid4().hex
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        dbs = [Database(uri, scope=s) for s in (scope, scope, scope + ':foreign')]
        for db in dbs:
            assert await db.connect()
        ctx, _, _ = build(tmp_path / 'ctx')
        stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
        managers = [CloneManager(ctx.settings, store) for store in stores]
        trigger = 'lifecycle_abort_' + uuid.uuid4().hex
        bot_id = 111111111
        try:
            for i in (0, 2):
                record = await stores[i].aadd(Clone(bot_id=bot_id, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
                assert record.lifecycle_generation == 1
            results = await asyncio.gather(*(store.afence(bot_id, disabled=False, expected_generation=1)
                for store in stores[:2]), return_exceptions=True)
            assert sum(isinstance(result, RuntimeError) for result in results) == 1
            await stores[0].aall()
            assert stores[0].get(bot_id).lifecycle_generation == 2
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(f'''CREATE FUNCTION {trigger}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN IF NEW.name = '{dbs[0].name_for("clones")}' THEN
                    RAISE EXCEPTION 'SYNTHETIC_PRIVATE_DB_VALUE'; END IF; RETURN NEW; END $$''')
                await conn.execute(f'CREATE TRIGGER {trigger} BEFORE UPDATE ON agent_documents FOR EACH ROW EXECUTE FUNCTION {trigger}()')
            with pytest.raises(RuntimeError) as error:
                await stores[0].afence(bot_id, disabled=True, expected_generation=2)
            assert 'SYNTHETIC_PRIVATE_DB_VALUE' not in str(error.value)
            assert stores[0].get(bot_id).lifecycle_generation == 2
            assert stores[0].get(bot_id).disabled is False
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', dbs[0].name_for(f'clone_lifecycle:{bot_id}'))
                assert (json.loads(raw) if isinstance(raw, str) else raw)['generation'] == 2
                await conn.execute(f'DROP TRIGGER {trigger} ON agent_documents')
            record = await stores[0].afence(bot_id, disabled=True, expected_generation=2)
            assert record.lifecycle_generation == 3
            for fields in ({'lifecycle_generation': 999}, {'owner_id': MEMBER + 1}, {'disabled': 'false'}):
                with pytest.raises(RuntimeError):
                    await stores[0].aupdate(bot_id, **fields)
            with pytest.raises(Exception):
                await managers[0].configuration.write(bot_id, actor_id=MEMBER + 1,
                    expected_revision=1, request_id='unauthorized', changes={'name': 'private'})
            await stores[2].aall()
            assert stores[2].get(bot_id).lifecycle_generation == 1
            assert stores[2].get(bot_id).disabled is False
            # Simulated process replacement reads the same durable generation.
            await dbs[1].load()
            fresh = CloneStore(tmp_path / 'fresh', db=dbs[1], box=SecretBox(KEY))
            assert fresh.get(bot_id).lifecycle_generation == 3
        finally:
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(f'DROP TRIGGER IF EXISTS {trigger} ON agent_documents')
                await conn.execute(f'DROP FUNCTION IF EXISTS {trigger}()')
            for db in dbs:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', db.scope + ':%')
                await db.close()
    asyncio.run(scenario())
