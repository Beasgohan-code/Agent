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
    '/encinfo extra', '/encpreset extra', '/encode fast extra', '/enccancel id extra'])
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


def test_cancel_only_owned_encoder_jobs():
    async def scenario():
        from agent.ui.theme import Theme
        jobs = SimpleNamespace(active=lambda: [Job('encode', 'encoder', 11), Job('leech', 'leech', 11), Job('other', 'encoder', 22)],
                               cancel=Mock(return_value=True))
        ctx = SimpleNamespace(theme=Theme(), jobs=jobs)
        await encoder.build(ctx)[1]['enccancel'](None, FakeMessage('/enccancel'))
        jobs.cancel.assert_called_once_with('encode', owner_id=11)
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
        async def communicate():
            entered.set()
            await asyncio.Event().wait()
        process = SimpleNamespace(returncode=None, communicate=communicate, kill=Mock(), wait=AsyncMock())
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
