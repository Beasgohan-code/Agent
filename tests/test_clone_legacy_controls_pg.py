"""Old interactive controls must not bypass revision-bound confirmation in PG."""
import asyncio
import os
import uuid

import pytest

from agent.modules import clone as clone_module
from agent.modules.clone.store import Clone
from agent.platform.db import Database
from test_clone import make_ctx, TOKEN_A, MEMBER, OWNER, FakeMessage
from test_clone_control_centre import private_query

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


@pytest.mark.parametrize('action', ['start', 'stop', 'restart', 'delete', 'delete_confirm'])
def test_saved_legacy_buttons_only_open_fresh_confirmation(tmp_path, action):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='legacy-cc:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx = make_ctx(tmp_path)
            ctx.db = db
            clone_module.build(ctx)
            store = ctx.clones._store
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            query = private_query(f'clone:{clone.bot_id}:{action}')
            await ctx.actions.dispatch(None, query)
            assert query.edits
            expected = 'delete' if action.startswith('delete') else action
            assert f'Confirm {expected}' in query.edits[-1][0]
            controls = str(query.edits[-1][1])
            assert f'cc:{clone.bot_id}:run:{expected}:{clone.configuration_revision}:{clone.lifecycle_generation}' in controls
            await store.aall()
            assert store.get(clone.bot_id).as_json() == clone.as_json()
            assert not ctx.clones.is_running(clone.bot_id)
            for uid in (999, OWNER):
                foreign = private_query(query.data, uid)
                await ctx.actions.dispatch(None, foreign)
                assert not foreign.edits and foreign.answers[-1][1]
            malformed = private_query(query.data + ':unexpected')
            await ctx.actions.dispatch(None, malformed)
            assert not malformed.edits and malformed.answers[-1][1]
            group = private_query(query.data)
            group.message.chat.id = -100
            await ctx.actions.dispatch(None, group)
            assert not group.edits and group.answers[-1][1]
        finally:
            await db.close()
    asyncio.run(scenario())


def test_delclone_is_owner_private_confirmation_and_stale_delete_is_fenced(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='legacy-delete:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx = make_ctx(tmp_path)
            ctx.db = db
            _, handlers = clone_module.build(ctx)
            store = ctx.clones._store
            clone = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            for uid in (OWNER, 999):
                denied = FakeMessage('/delclone 111111111', uid=uid)
                await handlers['delclone'](None, denied)
                assert store.get(clone.bot_id) is not None
                assert not denied.markups or denied.markups[-1] is None
            grouped = FakeMessage('/delclone 111111111')
            grouped.chat.id = -100
            await handlers['delclone'](None, grouped)
            assert not grouped.markups or grouped.markups[-1] is None
            assert store.get(clone.bot_id) is not None
            message = FakeMessage('/delclone 111111111')
            await handlers['delclone'](None, message)
            assert store.get(clone.bot_id) is not None
            assert 'Confirm delete' in message.replies[-1]
            await ctx.clones.configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                request_id='updated', changes={'name': 'new configuration'})
            stale = private_query(f'cc:{clone.bot_id}:run:delete:1:{clone.lifecycle_generation}')
            await ctx.actions.dispatch(None, stale)
            assert not stale.edits and stale.answers[-1][1]
            assert store.get(clone.bot_id).name == 'new configuration'
            current = store.get(clone.bot_id)
            confirmed = private_query(f'cc:{clone.bot_id}:run:delete:2:{current.lifecycle_generation}')
            await ctx.actions.dispatch(None, confirmed)
            assert store.get(clone.bot_id) is None
            assert 'Clone removed' in confirmed.edits[-1][0]
            # Recreated identity has a higher tombstone generation; old delete cannot apply.
            recreated = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            assert recreated.lifecycle_generation > current.lifecycle_generation
            replay = private_query(confirmed.data)
            await ctx.actions.dispatch(None, replay)
            assert not replay.edits and replay.answers[-1][1]
            assert store.get(clone.bot_id) is not None
        finally:
            await db.close()
    asyncio.run(scenario())


def test_atomic_delete_and_configuration_write_have_only_one_winner(tmp_path):
    from agent.modules.clone.store import CloneStore
    from agent.modules.clone.manager import CloneManager
    from agent.platform.secrets import SecretBox
    from test_atomic_clones import KEY
    async def scenario():
        scope = 'delete-cas:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
            ctx = make_ctx(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store) for store in stores]
            clone = await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            results = await asyncio.gather(
                managers[0].control(clone.bot_id, 'delete', actor_id=MEMBER, expected_revision=1,
                    expected_generation=clone.lifecycle_generation, request_id='delete_race'),
                managers[1].configuration.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                    request_id='config_race', changes={'name': 'winner'}), return_exceptions=True)
            assert sum(isinstance(result, BaseException) for result in results) == 1
            await stores[1].aall()
            remaining = stores[1].get(clone.bot_id)
            if isinstance(results[0], BaseException):
                assert remaining.name == 'winner' and remaining.configuration_revision == 2
            else:
                assert remaining is None
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval("SELECT string_agg(value::text,' ') FROM agent_documents WHERE name LIKE $1", scope + ':%')
            assert TOKEN_A not in raw
        finally:
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
