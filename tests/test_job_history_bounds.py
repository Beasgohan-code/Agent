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
