"""Grouped audio, contact-sheet and sample paths against real FFmpeg."""
import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import encoder as enc
from agent.modules.encoder.options import audio_options, screen_count
from agent.platform.jobs import Job, JobQueue
from agent.ui.theme import Theme
from test_modules import FakeMessage


@pytest.fixture(scope='module')
def av(tmp_path_factory):
    path = tmp_path_factory.mktemp('av-tools') / 'source.mp4'
    subprocess.run([enc.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc=duration=1:size=160x120:rate=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)],
                   check=True, timeout=30)
    return path


@pytest.mark.parametrize('kind,codec', [('mp3', 'mp3'), ('m4a', 'aac'), ('flac', 'flac')])
def test_real_audio_formats(av, tmp_path, kind, codec):
    output = tmp_path / ('audio.' + kind)
    asyncio.run(enc.run_tool(Job('audio', 'encoder', 1), enc.audio_command(av, output, kind=kind, bitrate=256), output, duration=1))
    info = asyncio.run(enc.probe(output))
    assert info['has_audio'] and not info['has_video'] and info['audio_codec'] == codec
    assert asyncio.run(enc.validate_output(output))


@pytest.mark.parametrize('count,columns', [(4, 2), (9, 3), (16, 4)])
def test_real_timestamp_contact_sheets(av, tmp_path, count, columns):
    output = tmp_path / f'sheet-{count}.jpg'
    asyncio.run(enc.run_tool(Job('sheet', 'encoder', 1), enc.screens_command(av, output, count=count, duration=1), output, duration=1))
    info = asyncio.run(enc.probe(output))
    assert info['width'] == 320 * columns
    assert info['height'] == 240 * columns
    assert asyncio.run(enc.validate_output(output))


@pytest.mark.parametrize('command', ['/toaudio wav', '/toaudio flac bitrate=128', '/toaudio mp3 bitrate=999',
    '/toaudio mp3 bitrate=192 extra', '/toaudio mp3 bitrate=128;rm', '/screens 5', '/screens 16 extra', '/screens ١٦'])
def test_invalid_tool_options_before_download(command):
    request = FakeMessage(command)
    request.reply_to_message = SimpleNamespace(download=AsyncMock())
    asyncio.run(enc.build(SimpleNamespace(theme=Theme()))[1][command.split()[0][1:]](None, request))
    request.reply_to_message.download.assert_not_awaited()
    assert 'Check Encoder options' in request.replies[-1]


def test_tool_defaults_preserved():
    assert audio_options([]) == ('mp3', 192)
    assert audio_options(['bitrate=320']) == ('mp3', 320)
    assert screen_count([]) == 9


@pytest.mark.parametrize('command,suffix', [('/toaudio m4a bitrate=128', '.m4a'), ('/toaudio flac', '.flac'), ('/screens 4', '.jpg')])
def test_handlers_route_options_through_job_and_output(av, command, suffix):
    async def scenario():
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue())
        request = FakeMessage(command)
        request.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(av)))
        await enc.build(ctx)[1][command.split()[0][1:]](None, request)
        job = ctx.jobs.for_owner(request.from_user.id)[0]
        assert job.state.value == 'done'
        output = enc.Path(job.result)
        try:
            assert output.suffix == suffix and output.stat().st_size > 0
        finally:
            output.unlink(missing_ok=True)
            output.parent.rmdir()
    asyncio.run(scenario())


def test_sample_beyond_end_fails_before_conversion(av, monkeypatch):
    async def scenario():
        runner = AsyncMock()
        monkeypatch.setattr(enc, 'run_tool', runner)
        ctx = SimpleNamespace(theme=Theme(), jobs=JobQueue())
        request = FakeMessage('/sample 10 1')
        request.reply_to_message = SimpleNamespace(video=True, download=AsyncMock(return_value=str(av)))
        await enc.build(ctx)[1]['sample'](None, request)
        assert ctx.jobs.for_owner(request.from_user.id)[0].state.value == 'failed'
        runner.assert_not_awaited()
    asyncio.run(scenario())
