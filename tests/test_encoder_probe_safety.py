"""Bound diagnostic memory and refuse implicit network protocol use in tools."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent.modules import encoder as enc


def process(monkeypatch, chunks):
    child = SimpleNamespace(returncode=None, stderr=SimpleNamespace(read=AsyncMock(side_effect=chunks)), kill=Mock(), wait=AsyncMock())
    monkeypatch.setattr(enc, 'ffmpeg_path', lambda: 'ffmpeg')
    monkeypatch.setattr(enc.asyncio, 'create_subprocess_exec', AsyncMock(return_value=child))
    return child


def test_noisy_probe_is_killed_before_unbounded_buffering(monkeypatch):
    child = process(monkeypatch, [b'x' * 8192] * 40)
    with pytest.raises(ValueError, match='inspection limit'):
        asyncio.run(enc.probe(enc.Path('input')))
    child.kill.assert_called_once()
    child.wait.assert_awaited_once()
    assert child.stderr.read.await_count <= 33


def test_probe_with_no_media_is_not_success(monkeypatch):
    process(monkeypatch, [b'Invalid data found when processing input', b''])
    with pytest.raises(ValueError, match='No supported'):
        asyncio.run(enc.probe(enc.Path('input')))


def test_small_metadata_can_span_chunks(monkeypatch):
    child = process(monkeypatch, [b'Duration: 00:00:01.00\nStream #0:0: Vi', b'deo: h264 160x120\n', b''])
    info = asyncio.run(enc.probe(enc.Path('input')))
    assert info['video_codec'] == 'h264' and info['duration'] == 1
    child.kill.assert_not_called()
    argv = enc.asyncio.create_subprocess_exec.await_args.args
    assert argv[argv.index('-protocol_whitelist')+1] == 'file,pipe'


def test_probe_timeout_reaps_child(monkeypatch):
    async def scenario():
        child = process(monkeypatch, [])
        async def block(size):
            await asyncio.Event().wait()
        child.stderr.read = block
        monkeypatch.setattr(enc, 'PROBE_TIMEOUT', 0.01)
        with pytest.raises(TimeoutError):
            await enc.probe(enc.Path('input'))
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('builder', [enc.build_command, enc.audio_command, enc.screens_command])
def test_each_conversion_builder_restricts_input_protocols(builder):
    command = builder(enc.Path('input'), enc.Path('output'))
    assert command[command.index('-protocol_whitelist')+1] == 'file,pipe'
    assert command.index('-protocol_whitelist') < command.index('-i')


def test_clip_builder_restricts_input_protocols():
    command = enc.clip_command(enc.Path('in'), enc.Path('out'), start=0, length=1)
    assert command[command.index('-protocol_whitelist')+1] == 'file,pipe'
