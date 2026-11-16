"""Real PostgreSQL reconciliation fences; no Telegram or production services."""
import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneManager
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, MEMBER, TOKEN_A

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


def test_reconciliation_fences_and_recovery(tmp_path):
    async def scenario():
        from agent.modules.clone.reconcile import CloneReconciler, ReconciliationError
        scope = 'reconcile:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        for db in dbs:
            assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=dbs[0], box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            clone = await store.aadd(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            repo = manager.configuration.repository
            calls = []
            worker_key = 'clone:111111111:agent'
            async def apply(config):
                calls.append(config.configuration_revision)
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute('''INSERT INTO agent_lease(name,holder,expires_at) VALUES($1,$2,EXTRACT(EPOCH FROM clock_timestamp())+60)
                        ON CONFLICT(name) DO UPDATE SET holder=$2,expires_at=EXCLUDED.expires_at''', worker_key, 'worker')
                return SimpleNamespace(owner='worker')
            r = CloneReconciler(repo)
            with pytest.raises(ReconciliationError):
                await r.run(clone.bot_id, revision=1, apply=None)  # crash before applying
            assert (await repo.read(clone.bot_id))['pending_revision'] == 1
            async def before_application(config):
                raise asyncio.CancelledError
            with pytest.raises(asyncio.CancelledError):
                await r.run(clone.bot_id, revision=1, apply=before_application)
            assert not calls
            assert (await repo.read(clone.bot_id))['pending_revision'] == 1
            result = await r.run(clone.bot_id, revision=1, apply=apply)
            assert result['applied_revision'] == 1
            assert calls == [1]
            async def existing_worker():
                return SimpleNamespace(owner="worker")
            await r.run(clone.bot_id, revision=1, apply=lambda config: existing_worker())
            assert calls == [1]
            async def update(expected, name):
                return await manager.configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=expected,
                    request_id=name, changes={'name': name})
            await update(1, 'second')
            async def fail(config):
                raise RuntimeError('PRIVATE_APPLICATION_SECRET')
            with pytest.raises(ReconciliationError) as error:
                await r.run(clone.bot_id, revision=2, apply=fail)
            assert 'PRIVATE_APPLICATION_SECRET' not in str(error.value)
            assert (await repo.read(clone.bot_id))['pending_revision'] == 2
            assert (await repo.applied_configuration(clone.bot_id)).configuration_revision == 1
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(config):
                await apply(config)
                entered.set()
                await release.wait()
                return SimpleNamespace(owner='worker')
            task = asyncio.create_task(r.run(clone.bot_id, revision=2, apply=blocked))
            await entered.wait()
            other_repo = type(repo)(dbs[1], box=SecretBox(KEY), validate=manager.settings_for)
            with pytest.raises(ReconciliationError):
                await CloneReconciler(other_repo).run(clone.bot_id, revision=2, apply=apply)
            await update(2, 'third')  # New desired commits during application.
            release.set()
            with pytest.raises(ReconciliationError):
                await task
            assert (await repo.read(clone.bot_id))['applied_revision'] == 1
            assert (await repo.read(clone.bot_id))['pending_revision'] == 3
            await r.run(clone.bot_id, revision=3, apply=apply)
            # A foreign controller scope cannot reuse this claim for an ack.
            foreign = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope + ':foreign')
            assert await foreign.connect()
            try:
                foreign_repo = type(repo)(foreign, box=SecretBox(KEY), validate=manager.settings_for)
                with pytest.raises(ReconciliationError):
                    await CloneReconciler(foreign_repo).run(clone.bot_id, revision=3, apply=apply)
                assert (await foreign_repo.read(clone.bot_id))['desired_revision'] == 0
            finally:
                await foreign.close()
            # Expiry after apply must not acknowledge; retry after a crash reapplies.
            await update(3, 'fourth')
            async def expired(config):
                result = await apply(config)
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute('UPDATE agent_lease SET expires_at=0 WHERE name=$1', worker_key)
                return result
            with pytest.raises(ReconciliationError):
                await r.run(clone.bot_id, revision=4, apply=expired)
            assert (await repo.read(clone.bot_id))['applied_revision'] == 3
            async def expired_claim(config):
                result = await apply(config)
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute('UPDATE agent_lease SET expires_at=0 WHERE name=$1', r.claim_key(clone.bot_id))
                return result
            with pytest.raises(ReconciliationError):
                await r.run(clone.bot_id, revision=4, apply=expired_claim)
            with pytest.raises(Exception):
                await repo.confirm_applied(clone.bot_id, revision=4)
            assert (await repo.read(clone.bot_id))['pending_revision'] == 4
            # Apply then cancellation simulates death before the ack transaction.
            async def crash(config):
                await apply(config)
                raise asyncio.CancelledError
            with pytest.raises(asyncio.CancelledError):
                await r.run(clone.bot_id, revision=4, apply=crash)
            assert (await repo.read(clone.bot_id))['pending_revision'] == 4
            await CloneReconciler(other_repo).run(clone.bot_id, revision=4, apply=apply)
            assert (await repo.read(clone.bot_id))['applied_revision'] == 4
            with pytest.raises(ReconciliationError):
                await r.run(clone.bot_id, revision=3, apply=apply)
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT string_agg(value::text,\' \') FROM agent_documents WHERE name LIKE $1', scope + ':%')
            assert TOKEN_A not in raw and 'PRIVATE_APPLICATION_SECRET' not in raw
        finally:
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
                await conn.execute('DELETE FROM agent_lease WHERE name LIKE $1 OR name=$2', scope + ':%', 'clone:111111111:agent')
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_manager_restart_and_supervision_share_revision_authority(tmp_path):
    async def scenario():
        from agent.platform.instance import InstanceLease
        from test_clone import FakeBot
        scope = 'manager-reconcile:' + uuid.uuid4().hex
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        db = Database(uri, scope=scope)
        assert await db.connect()
        workers = []
        ctx, _, _ = build(tmp_path / 'ctx')
        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.database = Database(uri, scope=settings.db_scope)
                self.lease = InstanceLease(tmp_path / 'unused', db=self.database)
                workers.append(self)
        store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
        manager = CloneManager(ctx.settings, store, factory=Worker)
        try:
            clone = await store.aadd(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            await manager.start(clone)
            assert (await manager.configuration.read(clone.bot_id))['applied_revision'] == 1
            await manager.configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                request_id='updated', changes={'profile': 'tiny'})
            await manager.supervise()
            assert (await manager.configuration.read(clone.bot_id))['applied_revision'] == 2
            assert manager.profile(clone.bot_id) == 'tiny'
            n = len(workers)
            await manager.start(clone)
            assert len(workers) == n
            await manager.restart(clone)
            assert (await manager.configuration.read(clone.bot_id))['applied_revision'] == 2
            await manager.stop_all()
            await manager.restore()
            assert manager.is_running(clone.bot_id)
        finally:
            await manager.stop_all()
            async with db._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
            await db.close()
    asyncio.run(scenario())
