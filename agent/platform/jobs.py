"""Agent — shared job queue.

One queue for every module (encoder, leech, filestore) instead of six private
ones. Jobs carry progress, can be cancelled, and never outlive shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class JobAdmissionError(RuntimeError):
    """No work admitted because the local queue is closed or at capacity."""


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    module: str
    owner_id: int
    label: str = ""
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    detail: str = ""
    #: Stable failure code only; provider exception bodies are not job history.
    error: str | None = None
    #: Whatever the runner returned — a produced file's path, usually.
    result: Any = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    task: asyncio.Task | None = None
    group_id: int | None = None

    @property
    def finished(self) -> bool:
        return self.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.module,
            "state": self.state.value,
            "progress": round(self.progress, 3),
            "detail": self.detail,
            "error": self.error,
            "result": None if self.result is None else str(self.result),
            "label": self.label,
        }


class JobQueue:
    """Bounded-concurrency runner with cancellation."""

    def __init__(self, *, concurrency: int = 2, max_history: int = 200, max_active: int = 100) -> None:
        if type(max_active) is not int or max_active < 1:
            raise ValueError("max_active must be a positive integer")
        self._max_active = max_active
        self._closed = False
        self.eligibility_check = None
        self._limit = asyncio.Semaphore(max(1, concurrency))
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._max_history = max_history
        self._tasks: set[asyncio.Task] = set()

    def ensure_capacity(self) -> None:
        """Synchronous preflight; submit rechecks. Do not await before admission."""
        if self._closed:
            raise JobAdmissionError("Job queue is shut down")
        # Count live tasks, not logical job states: cancellation may still be
        # cleaning up. No await between admission and task creation, so this
        # budget includes running, queued and cancelling work on this loop.
        if sum(not task.done() for task in self._tasks) >= self._max_active:
            raise JobAdmissionError("Job queue capacity reached; wait for active work to finish")

    def submit(
        self,
        module: str,
        owner_id: int,
        runner: Callable[[Job], Awaitable[Any]],
        *,
        label: str = "",
    ) -> Job:
        self.ensure_capacity()
        self._counter += 1
        job = Job(id=f"{module}-{self._counter}", module=module, owner_id=owner_id, label=label)
        from .execution import GROUP_EXECUTION
        scope = GROUP_EXECUTION.get()
        if scope is not None:
            group_id, slug = scope
            if slug != module:
                raise ValueError("Job module does not match its execution owner")
            job.group_id = group_id
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, runner), name=job.id)
        self._tasks.add(job.task)
        job.task.add_done_callback(self._tasks.discard)
        job.task.add_done_callback(lambda task: self._task_finished(job, task))
        self._trim()
        return job

    def _task_finished(self, job, task):
        self._finalize_cancel(job, task)
        self._trim()

    @staticmethod
    def _finalize_cancel(job, task):
        # Also runs when cancellation happens before _run starts or while
        # waiting for concurrency/admission checks outside the runner body.
        if task.cancelled():
            job.state = JobState.CANCELLED
            job.finished_at = job.finished_at or time.time()

    async def _run(self, job: Job, runner: Callable[[Job], Awaitable[Any]]) -> None:
        async with self._limit:
            if job.state is JobState.CANCELLED:
                return
            if job.group_id is not None and self.eligibility_check is not None:
                try:
                    eligible = await self.eligibility_check(job.group_id, job.module)
                except Exception:
                    eligible = False
                if not eligible:
                    job.state = JobState.CANCELLED
                    job.finished_at = time.time()
                    return
            # Eligibility is awaited: cancellation/shutdown may have happened
            # while the provider was reading, even if it swallowed CancelledError.
            # No await between this final fence and invoking the runner.
            if job.state is JobState.CANCELLED or self._closed:
                job.state = JobState.CANCELLED
                job.finished_at = job.finished_at or time.time()
                return
            job.state = JobState.RUNNING
            job.started_at = time.time()
            try:
                job.result = await runner(job)
            except asyncio.CancelledError:
                job.state = JobState.CANCELLED
                job.finished_at = time.time()
                raise
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                job.state = JobState.FAILED
                job.error = "runner_failed"
                job.finished_at = time.time()
                logger.warning("#Errors Job runner failed (%s).", type(exc).__name__)
            else:
                if job.state is JobState.CANCELLED:
                    job.result = None
                    job.finished_at = job.finished_at or time.time()
                    return
                job.state = JobState.DONE
                job.progress = 1.0
                job.finished_at = time.time()

    # -- control -----------------------------------------------------------

    def cancel(self, job_id: str, *, owner_id: int | None = None) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return False
        if owner_id is not None and job.owner_id != owner_id:
            return False
        job.state = JobState.CANCELLED
        job.finished_at = time.time()
        if job.task is not None:
            job.task.cancel()
        return True

    async def cancel_group(self, group_id: int, module: str) -> None:
        tasks = []
        # Logical cancellation can precede actual task completion. Include
        # already-cancelled work, without cancelling its cleanup a second time.
        for job in list(self._jobs.values()):
            if job.group_id == group_id and job.module == module:
                if not job.finished:
                    self.cancel(job.id)
                if (job.task is not None and not job.task.done()
                        and job.task is not asyncio.current_task()):
                    tasks.append(job.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def for_owner(self, owner_id: int) -> list[Job]:
        return [j for j in self._jobs.values() if j.owner_id == owner_id]

    def active(self) -> list[Job]:
        return [j for j in self._jobs.values() if not j.finished]

    async def shutdown(self) -> None:
        """Cancel everything still running; used on graceful stop."""
        self._closed = True
        for job in self.active():
            self.cancel(job.id)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _trim(self) -> None:
        if len(self._jobs) <= self._max_history:
            return
        finished = sorted(
            (j for j in self._jobs.values()
             if j.finished and (j.task is None or j.task.done())), key=lambda j: j.created_at
        )
        for job in finished[: len(self._jobs) - self._max_history]:
            self._jobs.pop(job.id, None)
