import asyncio
from unittest.mock import AsyncMock
from agent.modules import music
from agent.modules.music import sources
from agent.platform.net import LinkError
from test_music_controls import wire, invoke
from test_player_card import CHAT


def test_youtube_music_uses_shared_resolver_for_play_and_queue(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        monkeypatch.setattr(music, 'resolve', sources.resolve)
        monkeypatch.setattr(sources, 'check_target', AsyncMock())
        resolver = AsyncMock(return_value=('https://rr1.googlevideo.com/audio?token=private', 'Song.m4a'))
        monkeypatch.setattr(sources, 'resolve_audio', resolver)
        await invoke(handlers, '/play https://youtu.be/dQw4w9WgXcQ')
        resolver.assert_awaited_once_with('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        assert ctx.voice.playback(CHAT).title == 'Song'
        assert ctx.voice.playback(CHAT).source.startswith('https://rr1.googlevideo.com/')
        second = await invoke(handlers, '/playnext https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        assert 'Song' in second.reply.await_args.args[0]
        assert 'private' not in second.reply.await_args.args[0]
        assert ctx.voice.play.await_count == 1
    asyncio.run(scenario())


def test_typetube_failure_does_not_start_voice_or_break_direct_urls(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        monkeypatch.setattr(music, 'resolve', sources.resolve)
        monkeypatch.setattr(sources, 'check_target', AsyncMock())
        resolver = AsyncMock(side_effect=LinkError('TypeTube resolution unavailable'))
        monkeypatch.setattr(sources, 'resolve_audio', resolver)
        failed = await invoke(handlers, '/play https://youtu.be/dQw4w9WgXcQ')
        ctx.voice.play.assert_not_awaited()
        assert 'TypeTube resolution unavailable' in failed.reply.await_args.args[0]
        await invoke(handlers, '/play https://example.test/song.mp3')
        assert ctx.voice.playback(CHAT).title == 'song.mp3'
        assert resolver.await_count == 1
    asyncio.run(scenario())


def test_queued_youtube_refreshes_at_skip_and_keeps_queue_on_failure(tmp_path, monkeypatch, caplog):
    async def scenario():
        import logging
        caplog.set_level(logging.INFO, logger='agent.modules.music')
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        monkeypatch.setattr(music, 'resolve', sources.resolve)
        monkeypatch.setattr(sources, 'check_target', AsyncMock())
        admission = AsyncMock(return_value=('https://rr1.googlevideo.com/audio?token=OLD_PRIVATE', 'Song.m4a'))
        monkeypatch.setattr(sources, 'resolve_audio', admission)
        refresh = AsyncMock(side_effect=LinkError('PRIVATE_PROVIDER_ERROR'))
        monkeypatch.setattr(music, 'resolve_audio', refresh)
        await invoke(handlers, '/play https://example.test/current.mp3')
        await invoke(handlers, '/play https://youtu.be/dQw4w9WgXcQ')
        failed = await invoke(handlers, '/skip')
        assert ctx.voice.playback(CHAT).title == 'current.mp3'
        assert 'No queue change was confirmed' in failed.reply.await_args.args[0]
        assert 'PRIVATE_PROVIDER_ERROR' not in failed.reply.await_args.args[0]
        refresh.side_effect = None
        refresh.return_value = ('https://rr1.googlevideo.com/audio?token=NEW_PRIVATE', 'Song.m4a')
        await invoke(handlers, '/skip')
        refresh.assert_awaited_with('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        assert ctx.voice.playback(CHAT).source.endswith('token=NEW_PRIVATE')
        assert ctx.voice.playback(CHAT).title == 'Song'
        assert admission.await_count == 1
        assert 'OLD_PRIVATE' not in caplog.text and 'NEW_PRIVATE' not in caplog.text
    asyncio.run(scenario())


def test_initial_youtube_play_does_not_log_signed_source(tmp_path, monkeypatch, caplog):
    import logging
    async def scenario():
        caplog.set_level(logging.INFO, logger='agent.modules.music')
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        monkeypatch.setattr(music, 'resolve', sources.resolve)
        monkeypatch.setattr(sources, 'check_target', AsyncMock())
        monkeypatch.setattr(sources, 'resolve_audio', AsyncMock(return_value=(
            'https://rr1.googlevideo.com/audio?token=DO_NOT_LOG_THIS', 'Song.m4a')))
        await invoke(handlers, '/play https://youtu.be/dQw4w9WgXcQ')
        assert ctx.voice.playback(CHAT).title == 'Song'
        assert 'play started' in caplog.text
        assert 'DO_NOT_LOG_THIS' not in caplog.text
        assert 'googlevideo.com' not in caplog.text
    asyncio.run(scenario())


def test_replay_refreshes_youtube_without_losing_playback_on_provider_failure(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        monkeypatch.setattr(music, 'resolve', sources.resolve)
        monkeypatch.setattr(sources, 'check_target', AsyncMock())
        monkeypatch.setattr(sources, 'resolve_audio', AsyncMock(return_value=(
            'https://rr1.googlevideo.com/audio?old=secret', 'Song.m4a')))
        refresh = AsyncMock(side_effect=LinkError('PRIVATE_PROVIDER_ERROR'))
        monkeypatch.setattr(music, 'resolve_audio', refresh)
        await invoke(handlers, '/play https://youtu.be/dQw4w9WgXcQ')
        original = ctx.voice.playback(CHAT)
        failed = await invoke(handlers, '/replay')
        assert ctx.voice.playback(CHAT) is original
        assert ctx.voice.play.await_count == 1
        assert 'PRIVATE_PROVIDER_ERROR' not in failed.reply.await_args.args[0]
        refresh.side_effect = None
        refresh.return_value = ('https://rr1.googlevideo.com/audio?fresh=secret', 'Song.m4a')
        await invoke(handlers, '/replay')
        assert ctx.voice.playback(CHAT).source.endswith('fresh=secret')
        assert ctx.voice.play.await_count == 2
    asyncio.run(scenario())
