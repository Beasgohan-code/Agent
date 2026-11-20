"""Exhausting a queue preserves acknowledged intent until native leave succeeds."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType
from agent.modules import music
from agent.platform.voice import Playback, VoiceUnavailable
from test_player_card import build, FakeClient, FakeEngine, FakeQuery, CHAT, OWNER


@pytest.mark.parametrize('action', ['skip', 'natural', 'button'])
def test_empty_transition_failed_leave_keeps_current_for_recovery(tmp_path, monkeypatch, action):
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
        await invoke('/play final_track')
        ctx.voice.leave = AsyncMock(side_effect=VoiceUnavailable('private failure details'))
        if action == 'skip':
            notice = await invoke('/skip')
            assert 'not confirmed' in notice and 'private failure details' not in notice
        elif action == 'button':
            query = FakeQuery('music:skip', user_id=OWNER)
            await ctx.actions.dispatch(FakeClient(), query)
            assert any('not confirmed' in (text or '') for text, _ in query.answers)
        else:
            await ctx.voice.on_stream_end(CHAT)
        await invoke('/loop one')
        await ctx.voice.on_stream_end(CHAT)
        assert ctx.voice.play.await_count == 2
        assert ctx.voice.playback(CHAT).title == 'final_track'
        await invoke('/loop off')
        await invoke('/play recovery_next')
        # An erased queue would incorrectly start recovery_next immediately.
        assert ctx.voice.play.await_count == 2
        assert 'recovery_next' in await invoke('/queue')
        await invoke('/skip')
        assert ctx.voice.playback(CHAT).title == 'recovery_next'
        assert ctx.voice.play.await_count == 3
        async def leave(chat):
            ctx.voice.playbacks.pop(chat, None)
        ctx.voice.leave = AsyncMock(side_effect=leave)
        await invoke('/skip')
        assert 'Nothing queued' in await invoke('/queue')
        before = ctx.voice.play.await_count
        await ctx.voice.on_stream_end(CHAT)
        assert ctx.voice.play.await_count == before
    asyncio.run(scenario())
