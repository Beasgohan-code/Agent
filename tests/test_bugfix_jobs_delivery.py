"""Regression batch: queued task finalization and nonduplicating cached sends."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform.jobs import JobQueue, JobState
from agent.platform.storage import Storage
from agent.utils.delivery import send_stored


def test_direct_cancel_while_waiting_for_slot_finalizes_job():
    async def scenario():
        queue = JobQueue(concurrency=1)
        entered = asyncio.Event()
        async def block(job):
            entered.set()
            await asyncio.Event().wait()
        first = queue.submit('encoder', 1, block)
        await entered.wait()
        runner = AsyncMock()
        queued = queue.submit('leech', 2, runner)
        await asyncio.sleep(0)
        queued.task.cancel()
        await asyncio.gather(queued.task, return_exceptions=True)
        assert queued.state is JobState.CANCELLED and queued.finished_at is not None
        runner.assert_not_awaited()
        await queue.shutdown()
        assert first.finished_at is not None
    asyncio.run(scenario())


def test_cancel_before_first_task_step_and_shutdown_are_terminal():
    async def scenario():
        queue = JobQueue()
        runner = AsyncMock()
        job = queue.submit('encoder', 1, runner)
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        assert job.state is JobState.CANCELLED and job.finished_at is not None
        await queue.shutdown()
        await queue.shutdown()
        with pytest.raises(RuntimeError, match='shut down'):
            queue.submit('leech', 1, runner)
        runner.assert_not_awaited()
    asyncio.run(scenario())


def test_runner_swallowing_cancel_cannot_claim_success():
    async def scenario():
        queue = JobQueue()
        entered = asyncio.Event()
        async def runner(job):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return 'not-confirmed'
        job = queue.submit('leech', 1, runner)
        await entered.wait()
        assert queue.cancel(job.id, owner_id=1)
        await job.task
        assert job.state is JobState.CANCELLED and job.result is None
    asyncio.run(scenario())


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError('FLOOD_WAIT_10'), RuntimeError('CHAT_WRITE_FORBIDDEN')])
def test_ambiguous_cached_send_never_retries_disk(tmp_path, error):
    store = Storage(tmp_path)
    saved = store.save_bytes(1, 'file.bin', b'file')
    saved.telegram_file_id = 'cached'
    message = SimpleNamespace(reply_cached_media=AsyncMock(side_effect=error),
                              reply_document=AsyncMock(), reply_video=AsyncMock(), reply=AsyncMock())
    with pytest.raises(type(error)):
        asyncio.run(send_stored(message, store, saved))
    message.reply_document.assert_not_awaited()
    message.reply_video.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.parametrize('reason', ['FILE_ID_INVALID', 'FILE_REFERENCE_EXPIRED', 'FILE_REFERENCE_INVALID'])
def test_explicit_stale_reference_keeps_disk_fallback(tmp_path, reason):
    store = Storage(tmp_path)
    saved = store.save_bytes(1, 'file.bin', b'file')
    saved.telegram_file_id = 'cached'
    keyboard = object()
    message = SimpleNamespace(reply_cached_media=AsyncMock(side_effect=RuntimeError(reason)),
                              reply_document=AsyncMock(), reply=AsyncMock())
    assert asyncio.run(send_stored(message, store, saved, caption='caption', reply_markup=keyboard))
    assert message.reply_document.await_args.kwargs['reply_markup'] is keyboard
    assert message.reply_document.await_args.kwargs['caption'] == 'caption'


def test_local_send_timeout_does_not_report_false_refusal(tmp_path):
    store = Storage(tmp_path)
    saved = store.save_bytes(1, 'file.bin', b'file')
    message = SimpleNamespace(reply_document=AsyncMock(side_effect=TimeoutError()), reply=AsyncMock())
    with pytest.raises(TimeoutError):
        asyncio.run(send_stored(message, store, saved))
    message.reply.assert_not_awaited()
