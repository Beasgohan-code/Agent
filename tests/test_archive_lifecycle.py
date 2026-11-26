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


def test_recovery_reloads_local_only_records_retries_and_skips_missing_bytes(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(storage, 'ARCHIVE_RECOVERY_INTERVAL', 0.01)
        original = storage.Storage(tmp_path)
        saved = original.save_bytes(1, 'recover', b'data')
        missing = original.save_bytes(1, 'missing', b'lost')
        original.path_for(missing).unlink()
        restored = storage.Storage(tmp_path)
        attempts = []
        complete = asyncio.Event()
        async def upload(path, name):
            attempts.append(name)
            if len(attempts) == 1:
                raise ConnectionError('token=private_upload_error')
            complete.set()
            return 'cached-recovered'
        restored.attach_archive(upload)
        restored.start_archive_recovery()
        task = restored._archive_recovery
        restored.start_archive_recovery()
        assert restored._archive_recovery is task
        await asyncio.wait_for(complete.wait(), timeout=1)
        await restored.shutdown()
        assert attempts == ['recover', 'recover']
        assert restored._index[saved.id].telegram_file_id == 'cached-recovered'
        assert restored._index[missing.id].telegram_file_id == ''
        assert task.done() and restored._archive_recovery is None
        assert not restored._archive_tasks
        again = storage.Storage(tmp_path)
        assert again._index[saved.id].telegram_file_id == 'cached-recovered'
    asyncio.run(scenario())


def test_recovery_batches_do_not_starve_later_files_behind_failed_uploads(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(storage, 'ARCHIVE_RECOVERY_INTERVAL', 0.01)
        monkeypatch.setattr(storage, 'ARCHIVE_RECOVERY_BATCH', 1)
        store = storage.Storage(tmp_path)
        first = store.save_bytes(1, 'failing', b'a')
        second = store.save_bytes(1, 'working', b'b')
        complete = asyncio.Event()
        async def upload(path, name):
            if name == 'failing':
                raise ConnectionError('private backend failure')
            complete.set()
            return 'cached'
        store.attach_archive(upload)
        store.start_archive_recovery()
        await asyncio.wait_for(complete.wait(), timeout=1)
        await store.shutdown()
        assert first.telegram_file_id == ''
        assert second.telegram_file_id == 'cached'
    asyncio.run(scenario())


def test_archive_refuses_local_symlink_without_calling_uploader(tmp_path):
    async def scenario():
        store = storage.Storage(tmp_path / 'vault')
        saved = store.save_bytes(1, 'file', b'data')
        path = store.path_for(saved)
        path.unlink()
        secret = tmp_path / 'private'
        secret.write_text('private')
        path.symlink_to(secret)
        uploader = AsyncMock(return_value='should-not-upload')
        store.attach_archive(uploader)
        assert await store.archive(saved) == ''
        uploader.assert_not_awaited()
    asyncio.run(scenario())
