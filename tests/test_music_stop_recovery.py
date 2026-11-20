"""A failed voice Stop must not destroy the recoverable queue."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pyrogram.enums import ChatType
from agent.modules import music
from agent.platform.voice import Playback, VoiceUnavailable
from test_player_card import build, FakeClient, CHAT, OWNER, STRANGER


def test_stop_preserves_queue_on_failed_leave_and_clears_only_after_ack(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = build(tmp_path, monkeypatch)
        async def resolve(message, argument):
            return 'https://example.test/audio', argument
        monkeypatch.setattr(music, 'resolve', resolve)
        async def play(chat, source, *, title, requested_by):
            ctx.voice.playbacks[chat] = Playback(title, source, requested_by=requested_by)
        ctx.voice.play = AsyncMock(side_effect=play)
        async def invoke(text, chat=CHAT, uid=OWNER):
            m = SimpleNamespace(text=text, chat=SimpleNamespace(id=chat, type=ChatType.SUPERGROUP),
                                from_user=SimpleNamespace(id=uid), reply=AsyncMock())
            await handlers[text.split()[0][1:]](FakeClient(), m)
            return str(m.reply.await_args.args[0])
        await invoke('/play recover_current')
        await invoke('/play recover_waiting')
        await invoke('/play other_group', CHAT-1)
        before = await invoke('/queue')
        ctx.voice.leave = AsyncMock(side_effect=VoiceUnavailable('private failure details'))
        failed = await invoke('/stop')
        assert 'queue is preserved' in failed
        assert 'private failure details' not in failed
        assert 'Stopped and left' not in failed
        after = await invoke('/queue')
        assert 'recover_current' in before and 'recover_waiting' in before
        assert 'recover_current' in after and 'recover_waiting' in after
        attempts = ctx.voice.leave.await_count
        await invoke('/stop', uid=STRANGER)
        assert ctx.voice.leave.await_count == attempts
        assert 'recover_waiting' in await invoke('/queue')
        async def leave(chat):
            ctx.voice.playbacks.pop(chat, None)
        ctx.voice.leave = AsyncMock(side_effect=leave)
        success = await invoke('/stop')
        assert 'Stopped and left' in success
        assert 'Nothing queued' in await invoke('/queue')
        assert 'other_group' in await invoke('/queue', CHAT-1)
        assert ctx.voice.play.await_count == 2  # Stop never starts/advances a track.
    asyncio.run(scenario())
