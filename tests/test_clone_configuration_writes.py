"""Canonical revision writes on real concurrent PostgreSQL transactions."""
import asyncio
import os
import uuid

import pytest
from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneManager
from agent.modules.clone import revisions
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, TOKEN_A, MEMBER

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


def test_canonical_writes_cas_duplicates_restart_and_redaction(tmp_path):
    async def scenario():
        scope = 'config-write:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'context')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store) for store in stores]
            clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('encoder',))
            await stores[0].aadd(clone, owner_limit=3, total_limit=5)
            writers = [manager.configuration for manager in managers]
            initial = await writers[0].read(clone.bot_id)
            assert initial['desired_revision'] == initial['pending_revision'] == 1
            assert initial['applied_revision'] == 0
            async def update(index):
                return await writers[index].write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                    request_id='request' + str(index), changes={'profile': 'tiny', 'selected_plugins': ()})
            results = await asyncio.gather(update(0), update(1), return_exceptions=True)
            assert sum(isinstance(r, revisions.RevisionConflict) for r in results) == 1
            winning = next(i for i, r in enumerate(results) if not isinstance(r, BaseException))
            assert results[winning]['desired_revision'] == 2
            # Duplicate is durable, even after an intervening new configuration.
            await writers[0].write(clone.bot_id, actor_id=MEMBER, expected_revision=2,
                request_id='third', changes={'profile': 'files'})
            replay = await update(winning)
            assert replay['desired_revision'] == 2
            assert (await writers[0].read(clone.bot_id))['desired_revision'] == 3
            with pytest.raises(revisions.RevisionConflict):
                await writers[1].write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                    request_id='stale', changes={'profile': 'standard'})
            with pytest.raises(Exception) as error:
                await writers[0].write(clone.bot_id, actor_id=MEMBER, expected_revision=3,
                    request_id='invalid', changes={'selected_plugins': ('ops',), 'ai_api_key': 'PRIVATE_SECRET'})
            assert 'PRIVATE_SECRET' not in str(error.value)
            assert (await writers[0].read(clone.bot_id))['desired_revision'] == 3
            fresh = revisions.CloneConfigurationRevisions(dbs[1], box=SecretBox(KEY), validate=managers[1].settings_for)
            with pytest.raises(revisions.RevisionConflict):
                await fresh.pending_configuration(clone.bot_id, revision=2)
            assert (await fresh.pending_configuration(clone.bot_id, revision=3)).profile == 'files'
            assert await fresh.applied_configuration(clone.bot_id) is None
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT string_agg(value::text,\' \') FROM agent_documents WHERE name LIKE $1', scope + ':%')
            assert TOKEN_A not in raw and 'PRIVATE_SECRET' not in raw
        finally:
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
                    await db.close()
    asyncio.run(scenario())


def test_configuration_transaction_rollback_preserves_applied_and_cache(tmp_path):
    async def scenario():
        suffix = uuid.uuid4().hex
        scope = 'config-rollback:' + suffix
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope)
        assert await db.connect()
        trigger = 'config_abort_' + suffix
        try:
            ctx, _, _ = build(tmp_path / 'context')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            writer = manager.configuration
            clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('encoder',))
            await store.aadd(clone, owner_limit=3, total_limit=5)
            # Storage-level acknowledgement simulates a previously reconciled
            # revision; no live worker or automatic acknowledgement is added.
            await writer.repository.confirm_applied(clone.bot_id, revision=1)
            before = await writer.read(clone.bot_id)
            async with db._pool.acquire() as conn:
                await conn.execute(f'''CREATE FUNCTION {trigger}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN IF NEW.name = '{db.name_for("clones")}' THEN
                    RAISE EXCEPTION 'PRIVATE_DATABASE_SECRET'; END IF; RETURN NEW; END $$''')
                await conn.execute(f'CREATE TRIGGER {trigger} BEFORE UPDATE ON agent_documents FOR EACH ROW EXECUTE FUNCTION {trigger}()')
            with pytest.raises(Exception) as error:
                await writer.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                    request_id='retryable', changes={'profile': 'files', 'selected_plugins': ()})
            assert 'PRIVATE_DATABASE_SECRET' not in str(error.value)
            assert await writer.read(clone.bot_id) == before
            assert store.get(clone.bot_id).profile == 'standard'
            async with db._pool.acquire() as conn:
                assert await conn.fetchval('SELECT count(*) FROM agent_documents WHERE name=$1',
                    db.name_for('clone_configuration_request:111111111:retryable')) == 0
                await conn.execute(f'DROP TRIGGER {trigger} ON agent_documents')
            result = await writer.write(clone.bot_id, actor_id=MEMBER, expected_revision=1,
                request_id='retryable', changes={'profile': 'files', 'selected_plugins': ()})
            assert result['desired_revision'] == 2 and result['applied_revision'] == 1
            assert (await writer.repository.applied_configuration(clone.bot_id)).profile == 'standard'
            with pytest.raises(Exception):
                await store.aupdate(clone.bot_id, profile='tiny')
            with pytest.raises(Exception):
                await writer.write(clone.bot_id, actor_id=999, expected_revision=2,
                    request_id='unauthorized', changes={'profile': 'tiny'})
            assert (await writer.read(clone.bot_id))['desired_revision'] == 2
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute(f'DROP TRIGGER IF EXISTS {trigger} ON agent_documents')
                await conn.execute(f'DROP FUNCTION IF EXISTS {trigger}()')
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
            await db.close()
    asyncio.run(scenario())


def test_committed_desired_survives_connection_loss_before_reconciliation(tmp_path):
    async def scenario():
        scope = 'config-crash:' + uuid.uuid4().hex
        uri = os.environ['AGENT_TEST_DATABASE_URL']
        db = Database(uri, scope=scope)
        assert await db.connect()
        ctx, _, _ = build(tmp_path / 'context')
        try:
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            await store.aadd(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A), owner_limit=3, total_limit=5)
            await manager.configuration.write(111111111, actor_id=MEMBER, expected_revision=1,
                request_id='before_disconnect', changes={'profile': 'tiny'})
            await db.close()  # No worker reconciliation or acknowledgement.
            db = Database(uri, scope=scope)
            assert await db.connect()
            await db.load()
            restored = CloneStore(tmp_path / 'restored', db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, restored)
            state = await manager.configuration.read(111111111)
            assert state['desired_revision'] == state['pending_revision'] == 2
            assert state['applied_revision'] == 0
            assert restored.get(111111111).profile == 'tiny'
            replay = await manager.configuration.write(111111111, actor_id=MEMBER, expected_revision=1,
                request_id='before_disconnect', changes={'profile': 'tiny'})
            assert replay == state
            with pytest.raises(revisions.RevisionConflict):
                await manager.configuration.write(111111111, actor_id=MEMBER, expected_revision=1,
                    request_id='before_disconnect', changes={'profile': 'files'})
            assert (await manager.configuration.read(111111111)) == state
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', scope + ':%')
            await db.close()
    asyncio.run(scenario())
