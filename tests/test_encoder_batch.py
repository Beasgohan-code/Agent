"""Encoder batch option boundaries, subprocess lifecycle and cancellation scope."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agent.modules import encoder
from agent.platform.jobs import Job
from test_modules import FakeMessage


@pytest.mark.parametrize('command', ['/sample nan 30', '/sample inf 30', '/sample -1 30', '/sample 0 301',
    '/sample 0 0', '/sample text', '/sample 0 1 extra', '/compress extra', '/toaudio extra', '/screens 5',
    '/mediainfo extra', '/encode fast extra'])
def test_invalid_options_refused_before_download(command):
    async def scenario():
        from agent.ui.theme import Theme
        ctx = SimpleNamespace(theme=Theme())
        request = FakeMessage(command)
        request.reply_to_message = SimpleNamespace(download=AsyncMock())
        await encoder.build(ctx)[1][command.split()[0][1:]](None, request)
        request.reply_to_message.download.assert_not_awaited()
        assert 'Check Encoder options' in request.replies[-1]
    asyncio.run(scenario())


def test_noisy_stderr_cannot_block_conversion_runner(tmp_path):
    async def scenario():
        job = Job('test', 'encoder', 11)
        command = [sys.executable, '-c', 'import sys; sys.stderr.write("SECRET"*400000); sys.exit(2)']
        with pytest.raises(RuntimeError) as error:
            await asyncio.wait_for(encoder.run_tool(job, command, tmp_path / 'out', duration=1), timeout=5)
        assert 'SECRET' not in str(error.value) and 'exited 2' in str(error.value)
    asyncio.run(scenario())


def test_cancelled_probe_reaps_child(monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        async def read(size):
            entered.set()
            await asyncio.Event().wait()
        process = SimpleNamespace(returncode=None, stderr=SimpleNamespace(read=read), kill=Mock(), wait=AsyncMock())
        monkeypatch.setattr(encoder, 'ffmpeg_path', lambda: 'ffmpeg')
        monkeypatch.setattr(encoder.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
        task = asyncio.create_task(encoder.probe(encoder.Path('input')))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
    asyncio.run(scenario())


def test_conversion_deadline_reaps_process_and_removes_partial(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(encoder, 'CONVERSION_TIMEOUT', 0.1)
        output = tmp_path / 'partial.mp4'
        command = [sys.executable, '-c',
                   'import pathlib,time; pathlib.Path(__import__("sys").argv[1]).write_bytes(b"partial"); time.sleep(60)', str(output)]
        with pytest.raises(TimeoutError):
            await encoder.run_tool(Job('timeout', 'encoder', 1), command, output, duration=1)
        assert not output.exists()
    asyncio.run(scenario())


def test_success_exit_without_output_is_not_success(tmp_path):
    async def scenario():
        with pytest.raises(RuntimeError, match='nonempty output'):
            await encoder.run_tool(Job('empty', 'encoder', 1),
                                   [sys.executable, '-c', 'pass'], tmp_path / 'missing', duration=1)
    asyncio.run(scenario())


def test_cancel_validation_reaps_child(monkeypatch, tmp_path):
    async def scenario():
        entered = asyncio.Event()
        process = SimpleNamespace(returncode=None, kill=Mock())
        async def wait():
            if process.kill.called:
                process.returncode = -9
                return -9
            entered.set()
            await asyncio.Event().wait()
        process.wait = AsyncMock(side_effect=wait)
        monkeypatch.setattr(encoder, 'ffmpeg_path', lambda: 'ffmpeg')
        monkeypatch.setattr(encoder.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
        target = tmp_path / 'input'
        target.write_bytes(b'fake')
        task = asyncio.create_task(encoder.validate_output(target))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        process.kill.assert_called_once()
        assert process.wait.await_count == 2
    asyncio.run(scenario())


def test_validation_deadline_reaps_child(monkeypatch, tmp_path):
    async def scenario():
        process = SimpleNamespace(returncode=None, kill=Mock())
        async def wait():
            if process.kill.called:
                process.returncode = -9
                return -9
            await asyncio.Event().wait()
        process.wait = AsyncMock(side_effect=wait)
        monkeypatch.setattr(encoder, 'VALIDATION_TIMEOUT', 0.01)
        monkeypatch.setattr(encoder, 'ffmpeg_path', lambda: 'ffmpeg')
        monkeypatch.setattr(encoder.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
        target = tmp_path / 'input'
        target.write_bytes(b'fake')
        with pytest.raises(TimeoutError):
            await encoder.validate_output(target)
        process.kill.assert_called_once()
        assert process.wait.await_count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [TimeoutError, asyncio.CancelledError, RuntimeError])
def test_validation_failure_cleans_job_output(monkeypatch, tmp_path, failure):
    async def scenario():
        directory = tmp_path / 'owned'
        directory.mkdir()
        monkeypatch.setattr(encoder.tempfile, 'mkdtemp', lambda **kwargs: str(directory))
        monkeypatch.setattr(encoder, 'probe', AsyncMock(return_value={'duration': 1}))
        async def convert(job, src, output, **kwargs):
            output.write_bytes(b'partial')
            return output
        monkeypatch.setattr(encoder, 'run_ffmpeg', convert)
        monkeypatch.setattr(encoder, 'validate_output', AsyncMock(side_effect=failure))
        source = tmp_path / 'source.mp4'
        source.write_bytes(b'original')
        with pytest.raises(failure):
            await encoder.encode_job(Job('cleanup', 'encoder', 1), None, source, 'fast', 'h264')
        assert source.read_bytes() == b'original'
        assert not directory.exists()
    asyncio.run(scenario())
