"""Assistant-account ownership is global across bot tenants."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform.assistant import AssistantLease, AssistantBusy
from agent.platform.db import Database


def test_assistant_lease_refuses_unavailable_database():
    async def scenario():
        with pytest.raises(AssistantBusy, match='Database'):
            await AssistantLease(None).acquire(123)
    asyncio.run(scenario())


def test_assistant_lease_loss_invokes_cleanup_and_releases_without_self_cancel():
    async def scenario():
        connection = SimpleNamespace(is_closed=lambda: False,
                                     fetchval=AsyncMock(side_effect=[True, RuntimeError('lost'), True]))
        pool = SimpleNamespace(acquire=AsyncMock(return_value=connection), release=AsyncMock())
        guard = AssistantLease(SimpleNamespace(connected=True, _pool=pool), interval=0.001)
        await guard.acquire(123)
        assert guard.held
        finished = asyncio.Event()
        async def stop():
            # Mimic VoiceEngine.shutdown creating a child task for stop().
            await asyncio.wait_for(guard.release(), timeout=1)
            finished.set()
        guard.watch(stop)
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert not guard.held
        pool.release.assert_awaited_once()
    asyncio.run(scenario())


def test_busy_assistant_releases_pool_connection():
    async def scenario():
        connection = SimpleNamespace(is_closed=lambda: False, fetchval=AsyncMock(return_value=False))
        pool = SimpleNamespace(acquire=AsyncMock(return_value=connection), release=AsyncMock())
        guard = AssistantLease(SimpleNamespace(connected=True, _pool=pool))
        with pytest.raises(AssistantBusy, match='already in use'):
            await guard.acquire(123)
        assert not guard.held
        pool.release.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Dedicated Database required')
def test_real_postgres_assistant_lock_is_cross_tenant_and_reusable():
    async def scenario():
        url = os.environ['AGENT_TEST_DATABASE_URL']
        dbs = [Database(url, scope='assistant-test:' + uuid.uuid4().hex) for _ in range(3)]
        guards = []
        account = uuid.uuid4().int % (2**50) + 1
        try:
            for db in dbs:
                assert await db.connect()
                guards.append(AssistantLease(db))
            results = await asyncio.gather(*(guard.acquire(account) for guard in guards), return_exceptions=True)
            assert sum(result is None for result in results) == 1
            assert sum(isinstance(result, AssistantBusy) for result in results) == 2
            winner = next(guard for guard in guards if guard.held)
            loser = next(guard for guard in guards if not guard.held)
            other = next(guard for guard in guards if guard is not winner and guard is not loser)
            await other.acquire(account + 1)
            assert other.held  # Different account does not conflict.
            await winner.release()
            await loser.acquire(account)
            assert loser.held
        finally:
            for guard in guards:
                await guard.release()
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
