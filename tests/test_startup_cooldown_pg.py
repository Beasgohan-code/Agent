"""Real SQL regression, opt-in disposable database only."""
import asyncio
import os
import uuid

import pytest
from agent.platform.db import Database
from agent.platform.startup_cooldown import StartupCooldown


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Dedicated PostgreSQL required')
def test_cooldown_survives_new_controller_and_is_scoped_without_shortening():
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='test:' + uuid.uuid4().hex)
        assert await db.connect()
        other = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='test:' + uuid.uuid4().hex)
        assert await other.connect()
        try:
            first = StartupCooldown(db)
            assert await first.remaining() == 0
            await first.extend(300)
            assert 290 < await StartupCooldown(db).remaining() <= 300
            await first.extend(1)
            assert await first.remaining() > 290
            assert await StartupCooldown(other).remaining() == 0
            async with db._pool.acquire() as conn:
                await conn.execute("UPDATE agent_documents SET value='{\"retry_at\":1}'::jsonb WHERE name=$1",
                                   db.name_for('telegram_startup_cooldown'))
            assert await first.remaining() == 0
        finally:
            async with db._pool.acquire() as conn:
                await conn.execute('DELETE FROM agent_documents WHERE name=$1', db.name_for('telegram_startup_cooldown'))
            await other.close()
            await db.close()
    asyncio.run(scenario())
