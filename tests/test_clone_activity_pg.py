"""Durable lifecycle activity is owner-only, bounded and redacted."""
import asyncio
import json
import os
import uuid
import pytest
from agent.modules.clone.control_actions import CloneControlActions, ControlConflict
from agent.modules.clone.activity import read_activity
from agent.modules.clone.control_centre import CloneControlCentre
from agent.modules.clone.manager import CloneManager
from agent.modules.clone.store import Clone, CloneStore
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, MEMBER, OWNER, TOKEN_A, TOKEN_B
from test_clone_control_centre import private_query

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')


def test_activity_receipts_pagination_redaction_authority_and_outage(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='activity:' + uuid.uuid4().hex)
        assert await db.connect()
        try:
            ctx, _, _ = build(tmp_path / 'ctx')
            store = CloneStore(tmp_path, db=db, box=SecretBox(KEY))
            manager = CloneManager(ctx.settings, store)
            centre = CloneControlCentre(ctx, manager)
            a = await store.aadd(Clone(111111111, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            b = await store.aadd(Clone(222222222, MEMBER, TOKEN_B), owner_limit=3, total_limit=5)
            for i in range(8):
                a = await CloneControlActions(store).admit(a.bot_id, 'stop', actor_id=MEMBER, expected_revision=1,
                    expected_generation=a.lifecycle_generation, request_id=f'activity{i}')
            # A hostile/old receipt must never become raw UI text.
            async with db._pool.acquire() as conn:
                key = db.name_for('clone_control:111111111:activity7')
                raw = json.loads(await conn.fetchval('SELECT value::text FROM agent_documents WHERE name=$1', key))
                raw.update(last_error=TOKEN_A, action='<secret>', request_id=TOKEN_B)
                await conn.execute('UPDATE agent_documents SET value=$2::jsonb WHERE name=$1', key, json.dumps(raw))
            async def show(bot_id, page=0, uid=MEMBER):
                q = private_query(f'cc:{bot_id}:activity:{page}', uid)
                await centre.press(None, q, q.data.split(':', 1)[1])
                return q
            q = await show(a.bot_id)
            assert q.edits
            text, keys = q.edits[-1]
            assert 'admission' in text.lower() and 'not completion' in text.lower()
            assert TOKEN_A not in text and TOKEN_B not in text and '<secret>' not in text
            assert f'cc:{a.bot_id}:activity:1' in str(keys)
            assert 'Previous' in str((await show(a.bot_id, 1)).edits[-1][1])
            assert 'No lifecycle admissions' in (await show(b.bot_id)).edits[-1][0]
            for uid in (OWNER, 999):
                denied = await show(a.bot_id, uid=uid)
                assert not denied.edits and denied.answers[-1][1]
            assert not (await show(a.bot_id, 999)).edits
            for actor in (OWNER, 999):
                with pytest.raises(ControlConflict):
                    await read_activity(store, a.bot_id, actor)
            group = private_query(f'cc:{a.bot_id}:activity:0')
            group.message.chat.id = -100
            await centre.press(None, group, group.data.split(':', 1)[1])
            assert not group.edits and group.answers[-1][1]
            # History is retained across recreation of the same bot ID and explicitly labeled.
            await store.aremove(a.bot_id)
            with pytest.raises(ControlConflict):
                await read_activity(store, a.bot_id, MEMBER)
            recreated = await store.aadd(Clone(a.bot_id, MEMBER, TOKEN_A), owner_limit=3, total_limit=5)
            assert recreated.lifecycle_generation > a.lifecycle_generation
            assert 'retained across' in (await show(a.bot_id)).edits[-1][0]
            await db.close()
            assert not (await show(b.bot_id)).edits
        finally:
            await db.close()
    asyncio.run(scenario())
