"""Losing database ownership must never silently downgrade to a local lease."""
import asyncio
from unittest.mock import AsyncMock

from agent.platform.instance import InstanceLease


class Database:
    connected = True

    def __init__(self):
        self.take_lease = AsyncMock(return_value='taken')
        self.lease_holder = AsyncMock(return_value=(None, 0))


def test_renewal_failure_does_not_claim_ownership(tmp_path):
    async def scenario():
        db = Database()
        lease = InstanceLease(tmp_path / 'lock', db=db)
        assert await lease.acquire(wait_seconds=0)
        db.take_lease.return_value = 'unavailable'
        assert not await lease.beat_once()
        assert not lease.held
        assert lease.degraded
    asyncio.run(scenario())


def test_database_disconnect_does_not_switch_to_file_backend(tmp_path):
    async def scenario():
        db = Database()
        lease = InstanceLease(tmp_path / 'lock', db=db)
        assert await lease.acquire(wait_seconds=0)
        db.connected = False
        db.take_lease.return_value = 'unavailable'
        assert not await lease.beat_once()
        assert lease.backend == 'postgres'
        assert not (tmp_path / 'lock').exists()
    asyncio.run(scenario())


def test_heartbeat_exception_signals_shutdown(tmp_path):
    async def scenario():
        db = Database()
        lease = InstanceLease(tmp_path / 'lock', db=db, beat=0.001)
        assert await lease.acquire(wait_seconds=0)
        db.take_lease.side_effect = RuntimeError('network failed')
        stop = asyncio.Event()
        await asyncio.wait_for(lease.run_heartbeat(stop), 1)
        assert stop.is_set()
        assert not lease.held
    asyncio.run(scenario())
