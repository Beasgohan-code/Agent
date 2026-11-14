"""Seek parsing, permission boundaries and acknowledged native playback clock."""
import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules.music.seeking import seek_target
from agent.platform.voice import VoiceEngine, Playback, VoiceUnavailable
from test_music_controls import wire, invoke, CHAT, STRANGER


@pytest.mark.parametrize('raw,elapsed,expected', [('90', 0, 90), ('1:30', 0, 90), ('1:02:03', 0, 3723), ('+30s', 50, 80), ('-30s', 50, 20), ('+10', 50, 60), ('0', 50, 0)])
def test_seek_syntax(raw, elapsed, expected):
    assert seek_target(raw, elapsed) == expected


@pytest.mark.parametrize('raw', ['nan', 'inf', '١', '-90s', '1:60', '1:00:60', '999999999', '86401', '1;rm', '1.5', '+99999s', ''])
def test_bad_seek_targets(raw):
    with pytest.raises(ValueError):
        seek_target(raw, 10)


def native(monkeypatch):
    stream = SimpleNamespace(Flags=SimpleNamespace(IGNORE='ignore'))
    def media(source, **kwargs):
        return SimpleNamespace(source=source, **kwargs)
    media.Flags = stream.Flags
    monkeypatch.setitem(sys.modules, 'pytgcalls.types', SimpleNamespace(MediaStream=media))
    engine = VoiceEngine(session_string='secret', api_id=1, api_hash='secret')
    engine._connected = True
    engine._call = SimpleNamespace(play=AsyncMock())
    engine.playbacks[CHAT] = Playback('title', 'private-url', requested_by=11)
    return engine


def test_native_seek_updates_clock_after_ack_only(monkeypatch):
    async def scenario():
        engine = native(monkeypatch)
        await engine.seek(CHAT, 90)
        stream = engine._call.play.await_args.args[1]
        assert stream.ffmpeg_parameters == '-ss 90' and stream.video_flags == 'ignore'
        assert 90 <= engine.playback(CHAT).elapsed < 92
        before = engine.playback(CHAT).started_at
        engine._call.play.return_value = False
        with pytest.raises(VoiceUnavailable):
            await engine.seek(CHAT, 100)
        assert engine.playback(CHAT).started_at == before
    asyncio.run(scenario())


def test_native_seek_paused_or_failed_never_claims_new_position(monkeypatch):
    async def scenario():
        engine = native(monkeypatch)
        playback = engine.playback(CHAT)
        playback.paused_at = time.time()
        with pytest.raises(VoiceUnavailable, match='Resume'):
            await engine.seek(CHAT, 5)
        engine._call.play.assert_not_awaited()
        playback.paused_at = None
        before = playback.started_at
        engine._call.play.side_effect = RuntimeError('private-url secret')
        with pytest.raises(VoiceUnavailable) as error:
            await engine.seek(CHAT, 10)
        assert 'secret' not in str(error.value) and 'private-url' not in str(error.value)
        assert playback.started_at == before
    asyncio.run(scenario())


def test_seek_handler_permissions_and_queue_unchanged(tmp_path, monkeypatch):
    async def scenario():
        ctx, manifest, handlers = wire(tmp_path, monkeypatch)
        ctx.voice.seek = AsyncMock()
        assert 'seek' in manifest.commands
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play upcoming')
        denied = await invoke(handlers, '/seek 90', uid=STRANGER)
        assert 'administrators' in denied.reply.await_args.args[0]
        ctx.voice.seek.assert_not_awaited()
        await invoke(handlers, '/seek 1:30')
        ctx.voice.seek.assert_awaited_once_with(CHAT, 90)
        body = (await invoke(handlers, '/queue')).reply.await_args.args[0]
        assert 'current' in body and 'upcoming' in body
        await invoke(handlers, '/seek nan')
        assert ctx.voice.seek.await_count == 1
    asyncio.run(scenario())
