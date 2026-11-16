"""Lifecycle controls admit only current owner/revision/generation in PostgreSQL."""
import asyncio
import os
import uuid

import pytest

from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneManager
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, MEMBER, OWNER, TOKEN_A, TOKEN_B

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


def test_atomic_owner_revision_generation_admission_and_audit(tmp_path):
    from agent.modules.clone.control_actions import CloneControlActions, ControlConflict
    async def scenario():
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='control:' + uuid.uuid4().hex)]
        dbs.append(Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=dbs[0].scope))
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, s) for s in stores]
            clone = await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            actions = [CloneControlActions(s) for s in stores]
            common = dict(actor_id=MEMBER, expected_revision=clone.configuration_revision, expected_generation=clone.lifecycle_generation)
            for actor in (999, OWNER):
                with pytest.raises(ControlConflict):
                    await actions[0].admit(clone.bot_id, 'stop', **{**common, 'actor_id': actor}, request_id='foreign' + str(actor))
            async def admit(index):
                return await actions[index].admit(clone.bot_id, 'stop', **common, request_id=f'concurrent{index}')
            results = await asyncio.gather(admit(0), admit(1), return_exceptions=True)
            assert sum(isinstance(r, ControlConflict) for r in results) == 1
            admitted = next(r for r in results if not isinstance(r, BaseException))
            assert admitted.disabled
            assert admitted.lifecycle_generation > clone.lifecycle_generation
            with pytest.raises(ControlConflict):
                await actions[0].admit(clone.bot_id, 'start', **common, request_id='stale')
            await stores[1].aall()
            current = stores[1].get(clone.bot_id)
            await managers[1].configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                request_id='configchange', changes={'name': 'changed'})
            with pytest.raises(ControlConflict):
                await actions[0].admit(clone.bot_id, 'start', actor_id=MEMBER,
                    expected_revision=1, expected_generation=current.lifecycle_generation, request_id='oldconfig')
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval("SELECT string_agg(value::text,' ') FROM agent_documents WHERE name LIKE $1", dbs[0].scope + ':%')
            assert TOKEN_A not in raw
            assert 'concurrent' in raw and 'admitted' in raw
        finally:
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_manager_stop_control_persists_intent_and_rejects_replay(tmp_path):
    from agent.modules.clone.control_actions import ControlConflict
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='control-stop:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            other = await store.aadd(Clone(222222222, MEMBER, TOKEN_B), owner_limit=3, total_limit=5)
            fields = dict(actor_id=MEMBER, expected_revision=clone.configuration_revision,
                          expected_generation=clone.lifecycle_generation, request_id='stoponce')
            await manager.control(clone.bot_id, 'stop', **fields)
            restored = CloneStore(tmp_path / 'fresh', db=db, box=SecretBox(KEY))
            await restored.aall()
            assert restored.get(clone.bot_id).disabled
            assert restored.get(other.bot_id).as_json() == other.as_json()
            with pytest.raises(ControlConflict):
                await manager.control(clone.bot_id, 'stop', **fields)
        finally:
            await db.close()
    asyncio.run(scenario())


def test_controls_start_restart_reconcile_stop_use_real_reconciler_and_leases(tmp_path):
    from agent.platform.instance import InstanceLease
    from test_clone import FakeBot
    async def scenario():
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        db = Database(uri, scope='control-worker:' + uuid.uuid4().hex)
        assert await db.connect()
        workers = []
        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.database = Database(uri, scope=settings.db_scope)
                self.lease = InstanceLease(tmp_path / 'unused', db=self.database)
                workers.append(self)
        manager = None
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store, factory=Worker)
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A, profile='tiny'), owner_limit=3, total_limit=5)
            for index, action in enumerate(('start', 'restart', 'reconcile', 'stop')):
                await store.aall()
                current = store.get(clone.bot_id)
                result = await manager.control(clone.bot_id, action, actor_id=MEMBER,
                    expected_revision=current.configuration_revision, expected_generation=current.lifecycle_generation,
                    request_id='sequence' + str(index))
                assert result
                assert manager.is_running(clone.bot_id) == (action != 'stop')
                if action != 'stop':
                    state = await manager.configuration.read(clone.bot_id)
                    assert state['applied_revision'] == state['desired_revision'] == 1
                    assert manager._running_generations[clone.bot_id] == store.get(clone.bot_id).lifecycle_generation
            assert len(workers) == 3
            assert all(worker.client.stopped for worker in workers)
            assert store.get(clone.bot_id).disabled
        finally:
            if manager:
                await manager.stop_all()
            await db.close()
    asyncio.run(scenario())


def test_newer_remote_stop_fences_control_application_without_reviving_worker(tmp_path, monkeypatch):
    from agent.modules.clone.control_actions import CloneControlActions
    from agent.modules.clone.manager import CloneError
    from unittest.mock import Mock
    async def scenario():
        scope = 'control-race:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        entered, release = asyncio.Event(), asyncio.Event()
        task = None
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store) for store in stores]
            factory = Mock(side_effect=AssertionError('No stale worker may be constructed'))
            managers[0]._factory = factory
            original = CloneControlActions.admit
            async def delayed(self, *args, **kwargs):
                result = await original(self, *args, **kwargs)
                if kwargs['request_id'] == 'delayed':
                    entered.set()
                    await release.wait()
                return result
            monkeypatch.setattr(CloneControlActions, 'admit', delayed)
            clone = await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            task = asyncio.create_task(managers[0].control(clone.bot_id, 'start', actor_id=MEMBER,
                expected_revision=clone.configuration_revision, expected_generation=clone.lifecycle_generation, request_id='delayed'))
            await asyncio.wait_for(entered.wait(), 5)
            await stores[1].aall()
            current = stores[1].get(clone.bot_id)
            await managers[1].control(clone.bot_id, 'stop', actor_id=MEMBER,
                expected_revision=current.configuration_revision, expected_generation=current.lifecycle_generation, request_id='newstop')
            release.set()
            with pytest.raises(CloneError):
                await task
            factory.assert_not_called()
            await stores[0].aall()
            assert stores[0].get(clone.bot_id).disabled
            assert not managers[0].is_running(clone.bot_id)
            assert (await managers[0].configuration.read(clone.bot_id))['applied_revision'] == 0
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            for db in dbs:
                await db.close()
    asyncio.run(scenario())


def test_dashboard_stop_confirmation_executes_and_stale_replay_refuses(tmp_path):
    from agent.modules.clone.control_centre import CloneControlCentre
    from test_clone_control_centre import private_query
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='control-ui:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            centre = CloneControlCentre(ctx, manager)
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            suffix = f'stop:{clone.configuration_revision}:{clone.lifecycle_generation}'
            for foreign in (OWNER, 999):
                denied = private_query(f'cc:{clone.bot_id}:run:{suffix}', foreign)
                await centre.press(None, denied, denied.data.split(':', 1)[1])
                assert not denied.edits and denied.answers[-1][1]
                assert store.get(clone.bot_id).lifecycle_generation == clone.lifecycle_generation
            prompt = private_query(f'cc:{clone.bot_id}:ask:{suffix}')
            await centre.press(None, prompt, prompt.data.split(':', 1)[1])
            assert prompt.edits
            assert not store.get(clone.bot_id).disabled
            assert 'Confirm stop' in prompt.edits[-1][0]
            query = private_query(f'cc:{clone.bot_id}:run:{suffix}')
            await centre.press(None, query, query.data.split(':', 1)[1])
            assert store.get(clone.bot_id).disabled
            assert 'Stop intent saved' in query.edits[-1][0]
            replay = private_query(query.data)
            await centre.press(None, replay, replay.data.split(':', 1)[1])
            assert not replay.edits and replay.answers[-1][1]
            assert store.get(clone.bot_id).lifecycle_generation == clone.lifecycle_generation + 1
        finally:
            await db.close()
    asyncio.run(scenario())


def test_expired_entitlement_cannot_admit_start_but_stop_remains_allowed(tmp_path):
    from agent.modules.clone.manager import CloneError
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='control-entitlement:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            manager.eligible = lambda owner: False
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            fields = dict(actor_id=MEMBER, expected_revision=1, expected_generation=clone.lifecycle_generation)
            with pytest.raises(CloneError):
                await manager.control(clone.bot_id, 'start', **fields, request_id='expired')
            await store.aall()
            assert store.get(clone.bot_id).lifecycle_generation == clone.lifecycle_generation
            await manager.control(clone.bot_id, 'stop', **fields, request_id='allowedstop')
            assert store.get(clone.bot_id).disabled
        finally:
            await db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['remote_stop', 'configuration', 'recreate'])
def test_inflight_control_cannot_acknowledge_superseded_assignment(tmp_path, change):
    from agent.platform.instance import InstanceLease
    from agent.modules.clone.manager import CloneError
    from test_clone import FakeBot
    async def scenario():
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        scope = 'control-inflight:' + uuid.uuid4().hex
        dbs = [Database(uri, scope=scope) for _ in range(2)]
        entered, release = asyncio.Event(), asyncio.Event()
        task = None
        managers = []
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
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store, factory=Worker) for store in stores]
            clone = await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A, profile='tiny'), owner_limit=3, total_limit=5)
            task = asyncio.create_task(managers[0].control(clone.bot_id, 'start', actor_id=MEMBER,
                expected_revision=1, expected_generation=clone.lifecycle_generation, request_id='inflight'))
            await asyncio.wait_for(entered.wait(), 5)
            await stores[1].aall()
            current = stores[1].get(clone.bot_id)
            if change == 'remote_stop':
                await managers[1].control(clone.bot_id, 'stop', actor_id=MEMBER, expected_revision=1,
                    expected_generation=current.lifecycle_generation, request_id='supersede')
            elif change == 'configuration':
                await managers[1].configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                    request_id='newconfig', changes={'name': 'new revision'})
            else:
                await stores[1].aremove(clone.bot_id)
                await stores[1].aadd(Clone(111111111, MEMBER, TOKEN_A, profile='tiny'), owner_limit=3, total_limit=5)
            release.set()
            with pytest.raises(CloneError):
                await task
            assert not managers[0].is_running(clone.bot_id)
            assert all(worker.client.stopped for worker in workers)
            assert (await managers[0].configuration.read(clone.bot_id))['applied_revision'] == 0
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            for manager in managers:
                await manager.stop_all()
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
