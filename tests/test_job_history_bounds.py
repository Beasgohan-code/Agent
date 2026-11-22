"""Completion-time history pruning must not evict active work."""
import asyncio

from agent.platform.jobs import JobQueue, JobState


def test_completed_burst_trims_without_waiting_for_new_submission():
    async def scenario():
        queue = JobQueue(concurrency=8, max_history=3)
        event = asyncio.Event()
        async def run(job):
            await event.wait()
        jobs = [queue.submit('leech', 11, run) for _ in range(8)]
        assert len(queue.for_owner(11)) == 8
        event.set()
        await asyncio.gather(*(job.task for job in jobs))
        await asyncio.sleep(0)
        assert [job.id for job in queue.for_owner(11)] == [job.id for job in jobs[-3:]]
        assert all(job.state is JobState.DONE for job in jobs)
        await queue.shutdown()
    asyncio.run(scenario())


def test_pruning_preserves_running_work_and_cancelled_job_state():
    async def scenario():
        queue = JobQueue(concurrency=2, max_history=1)
        event = asyncio.Event()
        async def waiting(job):
            await event.wait()
        async def done(job):
            return None
        active = queue.submit('encoder', 11, waiting)
        completed = queue.submit('leech', 11, done)
        await completed.task
        await asyncio.sleep(0)
        assert queue.get(active.id) is active
        assert queue.get(completed.id) is None
        queue.cancel(active.id, owner_id=11)
        await asyncio.gather(active.task, return_exceptions=True)
        assert active.state is JobState.CANCELLED
        await queue.shutdown()
    asyncio.run(scenario())


def test_admission_bounds_running_and_waiting_tasks_without_allocating_rejected_jobs():
    import pytest
    async def scenario():
        queue = JobQueue(concurrency=1, max_active=2)
        gate = asyncio.Event()
        async def wait(job):
            await gate.wait()
        first = queue.submit('leech', 11, wait)
        second = queue.submit('encoder', 22, wait)
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match='capacity'):
            queue.submit('leech', 33, wait)
        assert len(queue._tasks) == 2 and queue._counter == 2
        assert not queue.for_owner(33)
        gate.set()
        await asyncio.gather(first.task, second.task)
        third = queue.submit('leech', 33, wait)
        assert third.id == 'leech-3'
        await third.task
        await queue.shutdown()
    asyncio.run(scenario())


def test_cancelled_work_keeps_admission_slot_until_cleanup_finishes():
    import pytest
    async def scenario():
        queue = JobQueue(concurrency=1, max_active=1)
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def work(job):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        job = queue.submit('leech', 11, work)
        await started.wait()
        queue.cancel(job.id)
        await cleaning.wait()
        with pytest.raises(RuntimeError, match='capacity'):
            queue.submit('encoder', 22, work)
        release.set()
        await asyncio.gather(job.task, return_exceptions=True)
        async def done(job):
            return 'ok'
        replacement = queue.submit('encoder', 22, done)
        await replacement.task
        assert replacement.result == 'ok'
        await queue.shutdown()
    asyncio.run(scenario())


def test_admission_budget_requires_positive_integer():
    import pytest
    for invalid in (0, -1, True, 1.5, '2', None):
        with pytest.raises(ValueError, match='positive integer'):
            JobQueue(max_active=invalid)
