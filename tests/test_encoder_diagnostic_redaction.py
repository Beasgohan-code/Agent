"""Encoder notifications/logs keep private source diagnostics off the wire."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import encoder
from agent.platform.jobs import Job, JobQueue, JobState
from agent.ui.theme import Theme
from test_modules import FakeMessage

PROBE = 'SYNTHETIC_PRIVATE_ENCODER_VALUE'


@pytest.mark.parametrize('command', ['/encode', '/compress', '/sample', '/toaudio', '/screens', '/mediainfo'])
def test_download_failure_never_logs_raw_provider_value(caplog, command):
    caplog.set_level(logging.DEBUG)

    async def scenario():
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue())
        message = FakeMessage(command)
        message.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(side_effect=RuntimeError(PROBE)))
        try:
            await encoder.build(ctx)[1][command[1:]](None, message)
            assert 'Could not download' in str(message.replies)
            assert PROBE not in str(message.replies)
            assert not ctx.jobs.for_owner(message.from_user.id)
        finally:
            await ctx.jobs.shutdown()
    asyncio.run(scenario())
    assert PROBE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.name == encoder.__name__)


@pytest.mark.parametrize('command', ['/encode', '/compress', '/sample', '/toaudio', '/screens'])
@pytest.mark.parametrize('failure', ['exception', 'timeout', 'false', 'none', 'missing_output', 'empty_output'])
def test_delivery_failure_preserves_completed_job_without_raw_path(tmp_path, monkeypatch, caplog, failure, command):
    caplog.set_level(logging.DEBUG)
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'input')
    output = tmp_path / PROBE / 'encoded.mp4'
    output.parent.mkdir()
    if failure != 'missing_output':
        output.write_bytes(b'' if failure == 'empty_output' else b'completed')
    monkeypatch.setattr(encoder, 'encode_job', AsyncMock(return_value=output))
    monkeypatch.setattr(encoder, 'run_tool', AsyncMock(return_value=output))
    monkeypatch.setattr(encoder, 'probe', AsyncMock(return_value={'duration': 1, 'has_audio': True, 'has_video': True}))

    async def scenario():
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue(), chats=None)
        message = FakeMessage(command)
        message.chat = SimpleNamespace(id=11)
        message.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(source)))
        client = SimpleNamespace(send_document=AsyncMock())
        if failure == 'exception':
            client.send_document.side_effect = RuntimeError(PROBE)
        elif failure == 'timeout':
            client.send_document.side_effect = TimeoutError(PROBE)
        elif failure in ('false', 'none'):
            client.send_document.return_value = False if failure == 'false' else None
        try:
            await encoder.build(ctx)[1][command[1:]](client, message)
            job, = ctx.jobs.for_owner(11)
            assert job.state is JobState.DONE and job.result == output
            assert 'not confirmed' in message.replies[-1] or 'sending it failed' in message.replies[-1]
            assert PROBE not in str(message.replies)
            assert client.send_document.await_count == (0 if failure in ('missing_output', 'empty_output') else 1)
            assert source.read_bytes() == b'input'
            if failure != 'missing_output':
                assert output.read_bytes() == (b'' if failure == 'empty_output' else b'completed')
        finally:
            await ctx.jobs.shutdown()
    asyncio.run(scenario())
    assert PROBE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.name == encoder.__name__)


@pytest.mark.parametrize('cancelled', [False, True])
@pytest.mark.parametrize('failed_cleanup', ['unlink', 'rmdir'])
def test_cleanup_failure_keeps_original_error_and_redacts_path(tmp_path, monkeypatch, caplog, failed_cleanup, cancelled):
    caplog.set_level(logging.DEBUG)
    owned = tmp_path / PROBE
    owned.mkdir()
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'original')
    monkeypatch.setattr(encoder.tempfile, 'mkdtemp', lambda **kwargs: str(owned))
    monkeypatch.setattr(encoder, 'probe', AsyncMock(return_value={'duration': 1}))
    original = asyncio.CancelledError('synthetic original failure') if cancelled else ValueError('synthetic original failure')
    monkeypatch.setattr(encoder, 'run_ffmpeg', AsyncMock(side_effect=original))
    real = getattr(encoder.Path, failed_cleanup)

    def fail(path, *args, **kwargs):
        if path == owned or path.parent == owned:
            raise PermissionError(PROBE)
        return real(path, *args, **kwargs)
    monkeypatch.setattr(encoder.Path, failed_cleanup, fail)

    async def scenario():
        with pytest.raises(type(original)) as error:
            await encoder.encode_job(Job('test', 'encoder', 11), None, source, 'fast', 'h264')
        assert error.value is original
        assert source.read_bytes() == b'original'
    asyncio.run(scenario())
    assert PROBE not in caplog.text and 'synthetic original failure' not in caplog.text
    records = [record for record in caplog.records if record.name == encoder.__name__]
    assert records and all(record.exc_info is None for record in records)


def test_acknowledged_delivery_sends_once_and_keeps_output(tmp_path, monkeypatch):
    output = tmp_path / 'encoded.mp4'
    output.write_bytes(b'completed')
    monkeypatch.setattr(encoder, 'encode_job', AsyncMock(return_value=output))

    async def scenario():
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue(), chats=None)
        message = FakeMessage('/encode')
        message.chat = SimpleNamespace(id=11)
        message.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(tmp_path / 'input.mp4')))
        client = SimpleNamespace(send_document=AsyncMock(return_value=SimpleNamespace(id=99)))
        try:
            await encoder.build(ctx)[1]['encode'](client, message)
            client.send_document.assert_awaited_once()
            assert client.send_document.await_args.args == (11, str(output))
            assert client.send_document.await_args.kwargs['file_name'] == output.name
            assert 'not confirmed' not in str(message.replies)
            assert ctx.jobs.for_owner(11)[0].state is JobState.DONE
            assert output.read_bytes() == b'completed'
        finally:
            await ctx.jobs.shutdown()
    asyncio.run(scenario())


def test_cancelled_upload_does_not_retry_or_claim_delivery(tmp_path, monkeypatch):
    output = tmp_path / 'encoded.mp4'
    output.write_bytes(b'completed')
    monkeypatch.setattr(encoder, 'encode_job', AsyncMock(return_value=output))

    async def scenario():
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue(), chats=None)
        message = FakeMessage('/encode')
        message.chat = SimpleNamespace(id=11)
        message.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(tmp_path / 'input.mp4')))
        client = SimpleNamespace(send_document=AsyncMock(side_effect=asyncio.CancelledError()))
        try:
            with pytest.raises(asyncio.CancelledError):
                await encoder.build(ctx)[1]['encode'](client, message)
            client.send_document.assert_awaited_once()
            assert ctx.jobs.for_owner(11)[0].state is JobState.DONE
            assert output.read_bytes() == b'completed'
            assert 'delivered' not in str(message.replies).lower()
        finally:
            await ctx.jobs.shutdown()
    asyncio.run(scenario())
