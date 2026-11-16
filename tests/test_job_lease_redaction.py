"""Failed job/lease diagnostics never retain or log provider exception bodies."""
import asyncio
import json
import logging
import os
import uuid

import pytest

from agent.platform.db import Database
from agent.platform.jobs import JobQueue, JobState


@pytest.mark.parametrize('unprintable', [False, True])
def test_failed_job_has_safe_retained_error_and_no_traceback(caplog, unprintable):
    probe = 'SYNTHETIC_PRIVATE_JOB_PROVIDER_VALUE'
    caplog.set_level(logging.DEBUG)

    class UnprintableError(RuntimeError):
        def __str__(self):
            raise AssertionError('Exception stringification is unsafe')

    async def scenario():
        queue = JobQueue()
        async def runner(job):
            raise UnprintableError(probe) if unprintable else RuntimeError(probe)
        try:
            job = queue.submit('encoder', 7, runner)
            await job.task
            assert job.state is JobState.FAILED
            assert job.error == 'runner_failed'
            assert job.finished_at is not None and job.result is None
            assert probe not in json.dumps(job.as_dict())
            assert queue.get(job.id) is job and queue.for_owner(8) == []
            assert not queue.cancel(job.id, owner_id=7)
            # One failure must not stop the queue accepting/completing later work.
            async def success(job):
                return 'done'
            next_job = queue.submit('encoder', 8, success)
            await next_job.task
            assert next_job.state is JobState.DONE and next_job.result == 'done'
        finally:
            await queue.shutdown()
    asyncio.run(scenario())
    assert probe not in caplog.text
    records = [record for record in caplog.records if record.name == 'agent.platform.jobs']
    assert len(records) == 1 and records[0].exc_info is None


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='PostgreSQL required')
def test_real_postgres_lease_errors_are_redacted_and_fail_closed(caplog):
    caplog.set_level(logging.DEBUG)
    probe = 'SYNTHETIC_PRIVATE_LEASE_DATABASE_VALUE'

    async def scenario():
        scope = 'lease-redaction:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=s) for s in (scope, scope + ':other')]
        function = 'reject_lease_' + uuid.uuid4().hex
        try:
            for db in dbs:
                assert await db.connect()
            db, other = dbs
            assert await db.take_lease('agent', 'original', 60) in ('taken', 'renewed')
            async with db._pool.acquire() as conn:
                await conn.execute(f'''CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN IF COALESCE(NEW.name, OLD.name) IN ('{db.lease_key('agent')}', '{db.lease_key('fresh')}') THEN
                    RAISE EXCEPTION '{probe}' USING DETAIL = 'synthetic private detail';
                    END IF; IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END $$''')
                await conn.execute(f'''CREATE TRIGGER {function} BEFORE INSERT OR UPDATE OR DELETE
                    ON agent_lease FOR EACH ROW EXECUTE FUNCTION {function}()''')
            assert await db.take_lease('agent', 'other-owner', 60) == 'unavailable'
            assert await db.take_lease('fresh', 'new-owner', 60) == 'unavailable'
            assert not await db.release_lease('agent', 'original')
            holder, _ = await db.lease_holder('agent')
            assert holder == 'original'  # Failed release did not silently succeed.
            assert await db.lease_holder('fresh') == (None, 0.0)
            replacement = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope)
            dbs.append(replacement)
            assert await replacement.connect()
            restored_holder, _ = await replacement.lease_holder('agent')
            assert restored_holder == 'original'  # Independent pool, not local state.
            assert await other.take_lease('agent', 'independent', 60) in ('taken', 'renewed')
            assert await other.release_lease('agent', 'independent')
            async with db._pool.acquire() as conn:
                await conn.execute(f'DROP TRIGGER {function} ON agent_lease')
            assert not await db.release_lease('agent', 'wrong-owner')
            assert await replacement.release_lease('agent', 'original')
            assert await replacement.take_lease('agent', 'replacement', 60) in ('taken', 'renewed')
        finally:
            if dbs[0]._pool:
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute(f'DROP TRIGGER IF EXISTS {function} ON agent_lease')
                    await conn.execute(f'DROP FUNCTION IF EXISTS {function}()')
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
    assert probe not in caplog.text and 'synthetic private detail' not in caplog.text
    records = [record for record in caplog.records if record.name == 'agent.platform.db' and record.levelno >= logging.WARNING]
    assert len(records) == 3 and all(record.exc_info is None for record in records)


def test_heartbeat_exception_stops_service_without_logging_body(tmp_path, caplog):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.platform.instance import InstanceLease

    caplog.set_level(logging.DEBUG)
    probe = 'SYNTHETIC_PRIVATE_HEARTBEAT_VALUE'

    async def scenario():
        db = SimpleNamespace(connected=True, take_lease=AsyncMock(return_value='taken'))
        lease = InstanceLease(tmp_path / 'lease.lock', db=db, beat=0.001)
        assert await lease.acquire(wait_seconds=0)
        db.take_lease.side_effect = RuntimeError(probe)
        stop = asyncio.Event()
        await asyncio.wait_for(lease.run_heartbeat(stop), timeout=1)
        assert stop.is_set() and lease.degraded and not lease.held
        assert lease.backend == 'postgres' and not lease.path.exists()
    asyncio.run(scenario())
    assert probe not in caplog.text
    records = [record for record in caplog.records if record.name == 'agent.platform.instance']
    assert records and all(record.exc_info is None for record in records)
