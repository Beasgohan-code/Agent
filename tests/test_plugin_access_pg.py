"""Opt-in tests against a dedicated PostgreSQL database, never production by default.

Run with AGENT_TEST_DATABASE_URL pointing at a disposable test database.
"""
import asyncio
import os
import uuid

import pytest

from agent.platform.db import Database
from agent.platform.plugin_access import PluginAccess, AccessError
from test_plugin_access import client, message

URL = os.environ.get('AGENT_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Dedicated AGENT_TEST_DATABASE_URL not supplied')


def test_postgres_slot_race_isolation_and_revocation():
    async def scenario():
        db = Database(URL, scope='test:' + uuid.uuid4().hex)
        assert await db.connect(), db.error
        service = PluginAccess(db, owner_id=11)
        try:
            for slug in ('music', 'filestore', 'encoder', 'leech'):
                await service.approve(slug, actor_id=11)
            results = await asyncio.gather(*(
                service.activate(client(), message(), slug)
                for slug in ('music', 'filestore', 'encoder', 'leech')
            ), return_exceptions=True)
            assert sum(result is True for result in results) == 3
            assert sum(isinstance(result, AccessError) for result in results) == 1
            active = [slug for slug in ('music', 'filestore', 'encoder', 'leech')
                      if await service.eligible(-100, slug)]
            assert len(active) == 3
            assert await service.activate(client(), message(-200), active[0])
            await service.configure(client(), message(), active[0], {'mode': 'group one'})
            await service.configure(client(), message(-200), active[0], {'mode': 'group two'})
            async with db._pool.acquire() as conn:
                rows = await conn.fetch('SELECT group_id,value FROM agent_plugin_config WHERE tenant=$1', db.scope)
                assert len(rows) == 2
                assert rows[0]['value'] != rows[1]['value']
            # Deactivation frees only this group's slot; other groups survive.
            assert await service.deactivate(client(), message(), active[1])
            assert await service.activate(client(), message(-200), active[1])
            async with db._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO agent_plugin_resources (tenant,group_id,slug,kind,resource_id) VALUES ($1,-100,$2,'job','test-job')",
                    db.scope, active[0],
                )
            # Approval-row locking must serialize revocation with activation.
            await asyncio.gather(
                service.revoke(active[0], actor_id=11),
                service.activate(client(), message(-300), active[0]),
                return_exceptions=True,
            )
            assert not await service.eligible(-300, active[0])
            async with db._pool.acquire() as conn:
                state = await conn.fetchval(
                    "SELECT state FROM agent_plugin_resources WHERE tenant=$1 AND resource_id='test-job'", db.scope,
                )
                assert state == 'cleanup_pending'
            assert await service.eligible(-200, active[1])
            assert not await service.eligible(-100, active[0])
            assert not await service.eligible(-200, active[0])
            with pytest.raises(AccessError, match='not approved'):
                await service.activate(client(), message(-300), active[0])
        finally:
            async with db._pool.acquire() as conn:
                for table in ('agent_plugin_resources', 'agent_plugin_config', 'agent_group_plugins',
                              'agent_plugin_history', 'agent_plugin_catalog'):
                    await conn.execute(f'DELETE FROM {table} WHERE tenant=$1', db.scope)
            await db.close()
    asyncio.run(scenario())
