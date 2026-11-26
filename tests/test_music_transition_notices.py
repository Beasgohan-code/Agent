"""Notification errors must never retry an already acknowledged voice action."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType
from agent.modules import music
from agent.platform.voice import Playback, VoiceUnavailable
from test_player_card import build, FakeClient, FakeEngine, CHAT, OWNER


@pytest.mark.parametrize('mode', ['success', 'send_failure', 'voice_failure'])
def test_transition_notices_do_not_duplicate_native_playback(tmp_path, monkeypatch, mode):
    async def scenario():
        monkeypatch.setattr(FakeEngine, 'set_stream_end_handler', lambda self, handler: setattr(self, 'on_stream_end', handler), raising=False)
        ctx, _, handlers = build(tmp_path, monkeypatch)
        async def resolve(message, argument):
            return 'https://example.test/audio', argument
        monkeypatch.setattr(music, 'resolve', resolve)
        async def play(chat, source, *, title, requested_by):
            ctx.voice.playbacks[chat] = Playback(title, source, requested_by=requested_by)
        ctx.voice.play = AsyncMock(side_effect=play)
        async def invoke(text):
            m = SimpleNamespace(text=text, chat=SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP),
                                from_user=SimpleNamespace(id=OWNER), reply=AsyncMock())
            await handlers[text.split()[0][1:]](FakeClient(), m)
            return str(m.reply.await_args.args[0])
        ctx.client = SimpleNamespace(send_message=AsyncMock())
        await invoke('/play first_track')
        await invoke('/play second_track')
        await invoke('/play third_track')
        if mode == 'send_failure':
            ctx.client.send_message.side_effect = RuntimeError('private transport failure')
        if mode == 'voice_failure':
            ctx.voice.play.side_effect = VoiceUnavailable('private voice failure')
        await ctx.voice.on_stream_end(CHAT)
        assert ctx.client.send_message.await_count == 1
        body = str(ctx.client.send_message.await_args.kwargs['text'])
        assert 'private' not in body
        if mode == 'voice_failure':
            assert 'not confirmed' in body and '/voicehealth' in body
            assert 'second_track' in await invoke('/queue')
        else:
            assert ctx.voice.play.await_count == 2
            assert ctx.voice.playback(CHAT).title == 'second_track'
            assert 'third_track' in await invoke('/queue')
            assert 'second_track' in body
        if mode == 'success':
            await ctx.voice.on_stream_end(CHAT)
            assert ctx.voice.playback(CHAT).title == 'third_track'
            await ctx.voice.on_stream_end(CHAT)
            assert 'Queue finished' in str(ctx.client.send_message.await_args.kwargs['text'])
            assert ctx.voice.playback(CHAT) is None
            count = ctx.client.send_message.await_count
            await ctx.voice.on_stream_end(CHAT)
            assert ctx.client.send_message.await_count == count
    asyncio.run(scenario())
