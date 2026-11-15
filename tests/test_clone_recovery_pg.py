"""Automatic recovery budget across controllers, opt-in disposable SQL only."""
import asyncio
import os
import uuid

import pytest
from agent.platform.db import Database
from agent.platform.clone_recovery import CloneRecovery


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Dedicated PostgreSQL required')
def test_restart_budget_is_durable_serialized_and_tenant_scoped():
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='test:' + uuid.uuid4().hex)
        other = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='test:' + uuid.uuid4().hex)
        assert await db.connect() and await other.connect()
        try:
            decisions = await asyncio.gather(*(CloneRecovery(db).reserve(123, 2) for _ in range(3)))
            assert decisions.count('ready') == 1 and decisions.count('waiting') == 2
            assert await CloneRecovery(other).reserve(123, 2) == 'ready'
            async with db._pool.acquire() as conn:
                # Advance prior admission, not the test clock: no wall-time sleep.
                await conn.execute("UPDATE agent_documents SET value=jsonb_build_object('attempts',jsonb_build_array(EXTRACT(EPOCH FROM clock_timestamp())-31)) WHERE name=$1", db.name_for('clone_recovery:123'))
            assert await CloneRecovery(db).reserve(123, 2) == 'ready'
            assert await CloneRecovery(db).reserve(123, 2) == 'exhausted'
            assert await CloneRecovery(db).reserve(456, 2) == 'ready'
        finally:
            for database in (db, other):
                async with database._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', database.name_for('clone_recovery:') + '%')
                await database.close()
    asyncio.run(scenario())
