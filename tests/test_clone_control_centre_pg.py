"""Dashboard refresh observes committed canonical writes, never cached JSON."""
import asyncio
import os
import uuid

import pytest

from agent.modules.clone.control_centre import CloneControlCentre
from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneManager
from agent.modules.clone.revisions import RevisionConflict
from agent.platform.db import Database
from agent.platform.secrets import SecretBox
from test_atomic_clones import KEY
from test_clone import build, TOKEN_A, TOKEN_B, MEMBER
from test_clone_control_centre import private_query

pytestmark = pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Database required')


def test_dashboard_reads_two_durable_configurations_after_concurrent_writes_and_deletion(tmp_path):
    async def scenario():
        scope = 'dashboard:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store) for store in stores]
            centre = CloneControlCentre(ctx, managers[1])
            await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A, name='A', selected_plugins=('encoder',), storage_channel=-100111), owner_limit=3, total_limit=5)
            await stores[0].aadd(Clone(222222222, MEMBER, TOKEN_B, name='B', selected_plugins=('postmaker',), storage_channel=-100222), owner_limit=3, total_limit=5)
            await stores[1].aall()
            async def change(index):
                return await managers[index].configuration.write(111111111, actor_id=MEMBER,
                    expected_revision=1, request_id=f'dashboard{index}', changes={'log_channel': -100333-index})
            results = await asyncio.gather(change(0), change(1), return_exceptions=True)
            assert sum(isinstance(result, RevisionConflict) for result in results) == 1
            for bot_id, own_channel, other_channel in ((111111111, '-100111', '-100222'), (222222222, '-100222', '-100111')):
                query = private_query(f'cc:{bot_id}:configuration')
                await centre.press(None, query, query.data.split(':', 1)[1])
                assert query.edits
                text = query.edits[-1][0]
                assert own_channel in text and other_channel not in text
                assert TOKEN_A not in text and TOKEN_B not in text
            assert (await managers[1].configuration.read(111111111))['desired_revision'] == 2
            assert (await managers[1].configuration.read(222222222))['desired_revision'] == 1
            # A second controller deletes after this dashboard cached the record.
            await stores[0].aremove(111111111)
            stale = private_query('cc:111111111:home')
            await centre.press(None, stale, '111111111:home')
            assert not stale.edits and stale.answers[-1][1]
            assert stores[1].get(111111111) is None
            # DB failure cannot silently render the remaining cached JSON record.
            await dbs[1].close()
            unavailable = private_query('cc:222222222:home')
            await centre.press(None, unavailable, '222222222:home')
            assert not unavailable.edits and unavailable.answers[-1][1]
        finally:
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
