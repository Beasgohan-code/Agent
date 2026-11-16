"""First Phase 3 storage contracts; disposable PostgreSQL only."""
import asyncio
import os
import uuid
from dataclasses import replace

import pytest
from agent.modules.clone import revisions
from agent.modules.clone.store import Clone
from agent.modules.clone.manager import CloneError
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import TOKEN_A, MEMBER, build

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


def test_revision_cas_encrypted_snapshots_and_restart(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='revision:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path)
            def repository():
                return revisions.CloneConfigurationRevisions(db, box=SecretBox(KEY), validate=ctx.clones.settings_for)
            a, b = repository(), repository()
            clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('encoder',))
            assert (await a.read(clone.bot_id))['configuration_status'] == 'untracked'
            results = await asyncio.gather(*(
                repo.propose(clone, expected_revision=0, request_id=uuid.uuid4().hex)
                for repo in (a, b)), return_exceptions=True)
            assert sum(isinstance(x, revisions.RevisionConflict) for x in results) == 1
            state = await repository().read(clone.bot_id)
            assert state['desired_revision'] == state['pending_revision'] == 1
            assert state['applied_revision'] == 0
            assert state['configuration_status'] == 'pending'
            await a.confirm_applied(clone.bot_id, revision=1)
            confirmed = await a.read(clone.bot_id)
            assert await a.confirm_applied(clone.bot_id, revision=1) == confirmed
            second = replace(clone, selected_plugins=('postmaker',))
            pending = await b.propose(second, expected_revision=1, request_id='second')
            assert pending['applied_revision'] == 1 and pending['desired_revision'] == 2
            with pytest.raises(revisions.RevisionConflict):
                await a.confirm_applied(clone.bot_id, revision=1)
            with pytest.raises(revisions.RevisionConflict):
                await a.record_failure(clone.bot_id, revision=1, code='old_failure')
            await b.record_failure(clone.bot_id, revision=2, code='initialization_failed')
            failed = await repository().read(clone.bot_id)
            assert failed['last_failed_revision'] == 2 and failed['applied_revision'] == 1
            assert failed['configuration_status'] == 'failed'
            applied = await repository().applied_configuration(clone.bot_id)
            assert applied.selected_plugins == ('encoder',)
            async with db._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT value::text FROM agent_documents WHERE name=$1', a.key(clone.bot_id))
            assert TOKEN_A not in raw
            assert failed['last_error_code'] == 'initialization_failed'
            assert failed['last_applied_at'] == confirmed['last_applied_at']
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', db.scope + ':%')
            await db.close()
    asyncio.run(scenario())


def test_revision_duplicate_invalid_request_and_tenant_isolation(tmp_path):
    async def scenario():
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='revision:' + uuid.uuid4().hex) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path)
            repos = [revisions.CloneConfigurationRevisions(db, box=SecretBox(KEY), validate=ctx.clones.settings_for) for db in dbs]
            clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('encoder',))
            first = await repos[0].propose(clone, expected_revision=0, request_id='same')
            assert await repos[0].propose(clone, expected_revision=0, request_id='same') == first
            with pytest.raises(revisions.RevisionConflict):
                await repos[0].propose(replace(clone, selected_plugins=('postmaker',)), expected_revision=0, request_id='same')
            with pytest.raises(CloneError):
                await repos[0].propose(replace(clone, selected_plugins=('ops',)), expected_revision=1, request_id='invalid')
            assert await repos[0].read(clone.bot_id) == first
            assert (await repos[1].read(clone.bot_id))['desired_revision'] == 0
        finally:
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', db.scope + ':%')
                    await db.close()
    asyncio.run(scenario())


def test_pending_configuration_read_is_revision_fenced(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='revision-read:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path)
            def repository():
                return revisions.CloneConfigurationRevisions(db, box=SecretBox(KEY), validate=ctx.clones.settings_for)
            repo = repository()
            clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('encoder',))
            await repo.propose(clone, expected_revision=0, request_id='first')
            assert (await repository().pending_configuration(clone.bot_id, revision=1)).token == TOKEN_A
            newer = replace(clone, name='New desired name')
            await repo.propose(newer, expected_revision=1, request_id='second')
            with pytest.raises(revisions.RevisionConflict):
                await repo.pending_configuration(clone.bot_id, revision=1)
            assert (await repository().pending_configuration(clone.bot_id, revision=2)).name == newer.name
            await repo.confirm_applied(clone.bot_id, revision=2)
            with pytest.raises(revisions.RevisionConflict):
                await repository().pending_configuration(clone.bot_id, revision=2)
            assert (await repository().applied_configuration(clone.bot_id)).name == newer.name
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name=$1', db.name_for('clone_configuration:111111111'))
            await db.close()
    asyncio.run(scenario())
