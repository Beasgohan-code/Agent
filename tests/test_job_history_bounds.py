"""Completion-time history pruning must not evict active work."""
import asyncio

import pytest

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


@pytest.mark.parametrize("mode", ["cancel", "shutdown"])
def test_cancelled_job_cannot_start_after_eligibility_suppresses_cancellation(mode):
    from unittest.mock import AsyncMock
    from agent.platform.execution import GROUP_EXECUTION
    async def scenario():
        queue = JobQueue()
        checking, finish_check, cancellation_seen = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def eligibility(group, module):
            checking.set()
            while not finish_check.is_set():
                try:
                    await finish_check.wait()
                except asyncio.CancelledError:
                    # A provider wrapper can absorb cancellation while finishing
                    # its read. Logical cancellation/shutdown must still win.
                    cancellation_seen.set()
            return True
        queue.eligibility_check = eligibility
        runner = AsyncMock(return_value='should not run')
        token = GROUP_EXECUTION.set((-100, 'group'))
        try:
            job = queue.submit('group', 11, runner)
        finally:
            GROUP_EXECUTION.reset(token)
        await checking.wait()
        shutdown = None
        if mode == 'cancel':
            assert queue.cancel(job.id, owner_id=11)
        else:
            shutdown = asyncio.create_task(queue.shutdown())
        await cancellation_seen.wait()
        finish_check.set()
        await job.task
        runner.assert_not_awaited()
        assert job.state is JobState.CANCELLED
        assert job.started_at is None and job.result is None
        assert job.finished_at is not None
        if shutdown is not None:
            await shutdown
        await queue.shutdown()
    asyncio.run(scenario())


def test_history_pruning_keeps_cancelled_job_while_cleanup_is_running():
    async def scenario():
        queue = JobQueue(concurrency=2, max_history=1)
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def work(job):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        job = queue.submit('encoder', 11, work)
        await started.wait()
        queue.cancel(job.id)
        await cleaning.wait()
        async def done(job):
            return None
        other = queue.submit('leech', 22, done)
        await other.task
        await asyncio.sleep(0)
        retained = queue.get(job.id)
        release.set()
        await asyncio.gather(job.task, return_exceptions=True)
        await queue.shutdown()
        assert retained is job
    asyncio.run(scenario())


def test_group_cancellation_waits_for_already_cancelled_cleanup():
    from agent.platform.execution import GROUP_EXECUTION
    async def scenario():
        queue = JobQueue()
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def work(job):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        token = GROUP_EXECUTION.set((-100, 'group'))
        try:
            job = queue.submit('group', 11, work)
        finally:
            GROUP_EXECUTION.reset(token)
        await started.wait()
        queue.cancel(job.id)
        await cleaning.wait()
        barrier = asyncio.create_task(queue.cancel_group(-100, 'group'))
        await asyncio.sleep(0)
        returned_early = barrier.done()
        release.set()
        await barrier
        await asyncio.gather(job.task, return_exceptions=True)
        await queue.shutdown()
        assert not returned_early
    asyncio.run(scenario())


def test_group_cancellation_does_not_touch_other_group_or_module():
    from agent.platform.execution import GROUP_EXECUTION
    async def scenario():
        queue = JobQueue(concurrency=3)
        gate = asyncio.Event()
        async def work(job):
            await gate.wait()
        jobs = []
        for group, module in ((-100, 'group'), (-200, 'group'), (-100, 'leech')):
            token = GROUP_EXECUTION.set((group, module))
            try:
                jobs.append(queue.submit(module, 11, work))
            finally:
                GROUP_EXECUTION.reset(token)
        await asyncio.sleep(0)
        await queue.cancel_group(-100, 'group')
        assert jobs[0].state is JobState.CANCELLED and jobs[0].task.done()
        assert all(job.state is JobState.RUNNING and not job.task.done() for job in jobs[1:])
        gate.set()
        await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)
        await queue.shutdown()
    asyncio.run(scenario())
