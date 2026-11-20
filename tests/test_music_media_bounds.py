"""Replied media admission is bounded even when Telegram metadata is absent."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.modules.music import sources


def request(download, size=0):
    return SimpleNamespace(reply_to_message=SimpleNamespace(audio=SimpleNamespace(file_size=size, title='Song'), download=download))


def test_download_timeout_is_bounded_and_cancelled(monkeypatch):
    async def scenario():
        cancelled = asyncio.Event()
        async def block(**kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(sources, 'DOWNLOAD_TIMEOUT', .01)
        with pytest.raises(sources.SourceError, match='timed out'):
            await sources.resolve(request(block), None)
        assert cancelled.is_set()
    asyncio.run(scenario())


def test_actual_oversized_download_is_not_admitted(tmp_path, monkeypatch):
    path = tmp_path / 'media'
    path.write_bytes(b'0123456789')
    monkeypatch.setattr(sources, 'BOT_DOWNLOAD_LIMIT', 5)
    with pytest.raises(sources.SourceError, match='limit'):
        asyncio.run(sources.resolve(request(AsyncMock(return_value=str(path))), None))
    assert path.exists()  # Resolver must not delete an arbitrary returned path.


def test_regular_nonempty_download_is_admitted(tmp_path):
    path = tmp_path / 'media'
    path.write_bytes(b'audio')
    assert asyncio.run(sources.resolve(request(AsyncMock(return_value=str(path))), None)) == (str(path), 'Song')


@pytest.mark.parametrize('kind', ['empty', 'missing', 'directory'])
def test_invalid_download_paths_are_rejected(tmp_path, kind):
    path = tmp_path / kind
    if kind == 'empty':
        path.touch()
    elif kind == 'directory':
        path.mkdir()
    with pytest.raises(sources.SourceError):
        asyncio.run(sources.resolve(request(AsyncMock(return_value=str(path))), None))


def test_progress_limit_and_cancellation_propagate(monkeypatch):
    async def scenario():
        async def too_large(**kwargs):
            await kwargs['progress'](sources.BOT_DOWNLOAD_LIMIT + 1, 0)
            return 'should-not-be-used'
        with pytest.raises(sources.SourceError, match='limit'):
            await sources.resolve(request(too_large), None)
        async def cancelled(**kwargs):
            raise asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await sources.resolve(request(cancelled), None)
    asyncio.run(scenario())


@pytest.mark.parametrize('size', [-1, '10', True, 1.5])
def test_invalid_size_metadata_never_starts_download(size):
    download = AsyncMock()
    with pytest.raises(sources.SourceError, match='metadata'):
        asyncio.run(sources.resolve(request(download, size=size), None))
    download.assert_not_awaited()


def test_symlink_download_is_not_admitted(tmp_path):
    target = tmp_path / 'real'
    target.write_bytes(b'audio')
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(sources.SourceError):
        asyncio.run(sources.resolve(request(AsyncMock(return_value=str(link))), None))
    assert target.read_bytes() == b'audio' and link.is_symlink()


def test_download_error_is_redacted(caplog):
    download = AsyncMock(side_effect=RuntimeError('PRIVATE_SESSION_VALUE'))
    with pytest.raises(sources.SourceError) as caught:
        asyncio.run(sources.resolve(request(download), None))
    assert 'PRIVATE_SESSION_VALUE' not in str(caught.value)
    assert 'PRIVATE_SESSION_VALUE' not in caplog.text
