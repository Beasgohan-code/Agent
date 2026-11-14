"""Archive upload coordination, bounded concurrency and graceful cancellation."""
import asyncio
from unittest.mock import AsyncMock


from agent.platform import storage


def test_concurrent_archive_requests_upload_once(tmp_path):
    async def scenario():
        store = storage.Storage(tmp_path)
        saved = store.save_bytes(1, 'file', b'data')
        async def upload(*args):
            await asyncio.sleep(0)
            return 'cached'
        uploader = AsyncMock(side_effect=upload)
        store.attach_archive(uploader)
        results = await asyncio.gather(*(store.archive(saved) for _ in range(5)))
        assert results == ['cached'] * 5
        uploader.assert_awaited_once()
    asyncio.run(scenario())


def test_duplicate_background_schedules_share_one_task(tmp_path):
    async def scenario():
        store = storage.Storage(tmp_path)
        saved = store.save_bytes(1, 'file', b'data')
        entered = asyncio.Event()
        async def upload(*args):
            entered.set()
            await asyncio.Event().wait()
        uploader = AsyncMock(side_effect=upload)
        store.attach_archive(uploader)
        for _ in range(5):
            store.schedule_archive(saved)
        await entered.wait()
        assert len(store._archive_tasks) == 1
        await store.shutdown()
        assert not store._archive_tasks
        assert saved.telegram_file_id == ''
        assert store.path_for(saved).read_bytes() == b'data'
        store.schedule_archive(saved)
        assert not store._archive_tasks
        assert await store.archive(saved) == ''
        uploader.assert_awaited_once()
    asyncio.run(scenario())


def test_archive_timeout_keeps_local_bytes(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(storage, 'ARCHIVE_TIMEOUT', 0.01)
        store = storage.Storage(tmp_path)
        saved = store.save_bytes(1, 'file', b'data')
        async def upload(*args):
            await asyncio.Event().wait()
        store.attach_archive(upload)
        assert await store.archive(saved) == ''
        assert saved.telegram_file_id == ''
        assert store.path_for(saved).read_bytes() == b'data'
    asyncio.run(scenario())


def test_background_persistence_errors_are_observed_and_task_released(tmp_path, monkeypatch, caplog):
    async def scenario():
        store = storage.Storage(tmp_path)
        saved = store.save_bytes(1, 'file', b'data')
        store.attach_archive(AsyncMock(return_value='cached'))
        def fail():
            raise RuntimeError('database unavailable')
        monkeypatch.setattr(store, '_save', fail)
        store.schedule_archive(saved)
        tasks = list(store._archive_tasks.values())
        await asyncio.gather(*tasks, return_exceptions=True)
        assert not store._archive_tasks
        assert saved.telegram_file_id == ''
        assert 'Archive persistence failed' in caplog.text
    asyncio.run(scenario())


def test_distinct_archive_uploads_have_bounded_concurrency(tmp_path):
    async def scenario():
        store = storage.Storage(tmp_path)
        files = [store.save_bytes(1, str(i), b'data') for i in range(5)]
        active = maximum = 0
        async def upload(*args):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            return 'cached'
        store.attach_archive(upload)
        assert await asyncio.gather(*(store.archive(saved) for saved in files)) == ['cached'] * 5
        assert maximum == 2
    asyncio.run(scenario())
