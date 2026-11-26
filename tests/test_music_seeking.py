"""Seek parsing, permission boundaries and acknowledged native playback clock."""
import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules.music.seeking import seek_target
from agent.platform.voice import VoiceEngine, Playback, VoiceUnavailable
from agent.platform import voice
from test_music_controls import wire, invoke, CHAT, STRANGER


@pytest.mark.parametrize('raw,elapsed,expected', [('90', 0, 90), ('1:30', 0, 90), ('1:02:03', 0, 3723), ('+30s', 50, 80), ('-30s', 50, 20), ('+10', 50, 60), ('0', 50, 0)])
def test_seek_syntax(raw, elapsed, expected):
    assert seek_target(raw, elapsed) == expected


@pytest.mark.parametrize('raw', ['nan', 'inf', '١', '-90s', '1:60', '1:00:60', '999999999', '86401', '1;rm', '1.5', '+99999s', ''])
def test_bad_seek_targets(raw):
    with pytest.raises(ValueError):
        seek_target(raw, 10)


def native(monkeypatch):
    # These tests isolate acknowledgement/clock behavior; boundary coverage lives
    # in test_native_media_safety with real local files and tool capability probes.
    monkeypatch.setattr(voice, 'local_source', lambda source: source)
    monkeypatch.setattr(voice, 'require_offline_options', AsyncMock())
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
        assert stream.ffmpeg_parameters == voice.POLICY + ' -ss 90' and stream.video_flags == 'ignore'
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


@pytest.mark.parametrize('raw,expected', [('5m', 300), ('1h', 3600), ('+5m', 700), ('-5m', 100), ('30s', 30)])
def test_duration_units(raw, expected):
    assert seek_target(raw, 400) == expected


@pytest.mark.parametrize('command,raw,expected', [('fw', '5m', 700), ('bw', '1m', 340), ('seekback', '30s', 370)])
def test_relative_shortcut_syntax(command, raw, expected):
    from agent.modules.music.seeking import control_target
    assert control_target(command, raw, 400) == expected


@pytest.mark.parametrize('command,raw', [('fw', '-1'), ('bw', '+30'), ('fw', '0'), ('bw', '1h'), ('seekback', '1:30'), ('fw', '25h')])
def test_shortcuts_reject_ambiguous_or_out_of_range_values(command, raw):
    from agent.modules.music.seeking import control_target
    with pytest.raises(ValueError):
        control_target(command, raw, 30)


@pytest.mark.parametrize('command,arg,expected', [('fw', '5m', 900), ('bw', '1m', 540), ('seekback', '30s', 570)])
def test_shortcut_handlers_preserve_queue_and_deny_nonadmins(tmp_path, monkeypatch, command, arg, expected):
    async def scenario():
        ctx, manifest, handlers = wire(tmp_path, monkeypatch)
        assert command in manifest.commands
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play upcoming')
        ctx.voice.playbacks[CHAT] = SimpleNamespace(elapsed=600, paused=False, title='current')
        ctx.voice.seek = AsyncMock()
        await invoke(handlers, f'/{command} {arg}', uid=STRANGER)
        ctx.voice.seek.assert_not_awaited()
        await invoke(handlers, f'/{command} {arg}')
        ctx.voice.seek.assert_awaited_once_with(CHAT, expected)
        body = (await invoke(handlers, '/queue')).reply.await_args.args[0]
        assert 'upcoming' in body
    asyncio.run(scenario())


def test_cancelled_native_seek_does_not_update_position(monkeypatch):
    async def scenario():
        engine = native(monkeypatch)
        before = engine.playback(CHAT).started_at
        entered = asyncio.Event()
        async def wait(*args):
            entered.set()
            await asyncio.Event().wait()
        engine._call.play.side_effect = wait
        task = asyncio.create_task(engine.seek(CHAT, 90))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.playback(CHAT).started_at == before
    asyncio.run(scenario())


def test_timed_out_native_seek_does_not_update_position(monkeypatch):
    async def scenario():
        from agent.platform import voice
        monkeypatch.setattr(voice, 'START_TIMEOUT', 0.01)
        engine = native(monkeypatch)
        before = engine.playback(CHAT).started_at
        async def wait(*args):
            await asyncio.Event().wait()
        engine._call.play.side_effect = wait
        with pytest.raises(VoiceUnavailable, match='TimeoutError'):
            await engine.seek(CHAT, 90)
        assert engine.playback(CHAT).started_at == before
    asyncio.run(scenario())
