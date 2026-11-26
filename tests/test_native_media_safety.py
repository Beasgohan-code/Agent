"""Native URL handoff is not a redirect/DNS enforcement boundary."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform.voice import Playback, VoiceEngine, VoiceUnavailable


@pytest.mark.parametrize('source', [
    'https://public.example/redirect-to-private',
    'http://127.0.0.1/private',
    'https://rebinding.example/audio',
    'https://rr1.googlevideo.com/audio?signed=PRIVATE',
    'concat:http://127.0.0.1/a|http://127.0.0.1/b',
])
@pytest.mark.parametrize('operation', ['play', 'seek', 'seek_existing'])
def test_unmediated_remote_source_never_reaches_native(source, operation):
    async def scenario():
        engine = VoiceEngine(session_string='private', api_id=1, api_hash='private')
        engine._connected = True
        engine._call = SimpleNamespace(play=AsyncMock())
        original = Playback('old', source if operation == 'seek_existing' else '/existing/local')
        engine.playbacks[-100] = original
        with pytest.raises((VoiceUnavailable, TypeError)):
            if operation == 'play':
                await engine.play(-100, source, title='new')
            elif operation == 'seek':
                await engine.seek(-100, 10, source=source)
            else:
                await engine.seek(-100, 10)
        engine._call.play.assert_not_awaited()
        assert engine.playbacks[-100] is original
    asyncio.run(scenario())


def tools(tmp_path, monkeypatch, help_text):
    for name in ('ffmpeg', 'ffprobe'):
        path = tmp_path / name
        path.write_text("#!/bin/sh\nprintf '%s\\n' '" + help_text + "'\n")
        path.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))


def test_local_policy_reaches_installed_stream_and_probe_command(tmp_path, monkeypatch):
    from pytgcalls.ffmpeg import build_command, cleanup_commands
    from agent.platform.native_media import POLICY

    tools(tmp_path, monkeypatch, '-protocol_whitelist list\n-format_whitelist list\n-ss value')
    media = tmp_path / 'audio.wav'
    media.write_bytes(b'fixture, not a decoded audio test')

    async def scenario():
        engine = VoiceEngine(session_string='private', api_id=1, api_hash='private')
        engine._connected = True
        engine._call = SimpleNamespace(play=AsyncMock())
        await engine.play(-100, str(media), title='local')
        stream = engine._call.play.await_args.args[1]
        assert stream._ffmpeg_parameters == POLICY
        for binary in ('ffmpeg', 'ffprobe'):
            command = build_command(binary, stream._ffmpeg_parameters, str(media), stream._audio_parameters)
            command = await cleanup_commands(command)
            assert command.index('-protocol_whitelist') < command.index('-i')
            assert command[command.index('-protocol_whitelist') + 1] == 'file,pipe'
            assert command.index('-format_whitelist') < command.index('-i')
            formats = command[command.index('-format_whitelist') + 1].split(',')
            assert not {'hls', 'dash', 'concat', 'sdp', 'image2'} & set(formats)
        await engine.seek(-100, 5)
        assert engine._call.play.await_args.args[1]._ffmpeg_parameters == POLICY + ' -ss 5'
    asyncio.run(scenario())


@pytest.mark.parametrize('help_text', ['', '-protocol_whitelist list', '-format_whitelist list'])
def test_missing_security_options_fail_closed(tmp_path, monkeypatch, help_text):
    tools(tmp_path, monkeypatch, help_text)
    media = tmp_path / 'audio.wav'
    media.write_bytes(b'fixture')

    async def scenario():
        engine = VoiceEngine(session_string='private', api_id=1, api_hash='private')
        engine._connected = True
        engine._call = SimpleNamespace(play=AsyncMock())
        with pytest.raises(VoiceUnavailable, match='offline'):
            await engine.play(-100, str(media), title='local')
        engine._call.play.assert_not_awaited()
        assert not engine.playbacks
    asyncio.run(scenario())


def test_invalid_local_inputs_rejected_without_native_io(tmp_path):
    from agent.platform.native_media import local_source, NativeMediaError
    for source in (str(tmp_path), str(tmp_path / 'missing'), '/dev/null', 'file:/etc/passwd', '//host/share', '\\host\\share', 'a\nb'):
        with pytest.raises(NativeMediaError):
            local_source(source)


def test_capability_probe_timeout_reaps_subprocess(tmp_path, monkeypatch):
    from agent.platform import native_media
    path = tmp_path / 'ffmpeg'
    path.write_text('#!/bin/sh\nexec /bin/sleep 30\n')
    path.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.setattr(native_media, 'PROBE_TIMEOUT', 0.02)
    real_create = asyncio.create_subprocess_exec
    children = []

    async def create(*args, **kwargs):
        child = await real_create(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(native_media.asyncio, 'create_subprocess_exec', create)

    async def scenario():
        with pytest.raises(native_media.NativeMediaError, match='unavailable'):
            await native_media.require_offline_options()
        assert children and all(child.returncode is not None for child in children)
        monkeypatch.setattr(native_media, 'PROBE_TIMEOUT', 5)
        task = asyncio.create_task(native_media.require_offline_options())
        for _ in range(100):
            if len(children) == 2:
                break
            await asyncio.sleep(0.01)
        assert len(children) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(child.returncode is not None for child in children)
    asyncio.run(scenario())


def test_real_engine_rejects_remote_queue_admission(tmp_path, monkeypatch):
    from agent.modules import music
    from test_music_controls import wire, invoke, CHAT

    async def scenario():
        ctx, _, _ = wire(tmp_path, monkeypatch)
        engine = VoiceEngine(session_string='private', api_id=1, api_hash='private')
        engine._connected = True
        engine._call = SimpleNamespace(play=AsyncMock())
        # Membership is a separate Telegram boundary, not exercised here.
        engine.join_music_group = AsyncMock()
        engine.playbacks[CHAT] = Playback('already playing', '/existing/local')
        ctx.voice = engine
        _, handlers = music.build(ctx)
        response = await invoke(handlers, '/play https://public.example/redirect')
        body = response.reply.await_args.args[0]
        assert 'disabled' in body and 'Added to queue' not in body
        engine._call.play.assert_not_awaited()
        assert engine.playbacks[CHAT].title == 'already playing'
        listing = await invoke(handlers, '/queue')
        assert 'public.example' not in listing.reply.await_args.args[0]
    asyncio.run(scenario())
