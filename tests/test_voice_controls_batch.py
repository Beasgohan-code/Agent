"""Bounded native controls and honest handler output under uncertain outcomes."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform import voice
from test_music_controls import wire, invoke, CHAT


def engine():
    worker = voice.VoiceEngine(session_string='secret', api_id=1, api_hash='secret')
    worker._connected = True
    worker._call = SimpleNamespace(**{name: AsyncMock() for name in ('play', 'pause', 'resume', 'leave_call', 'change_volume_call')})
    worker.playbacks[CHAT] = voice.Playback('original', 'private-source', requested_by=1)
    return worker


async def operate(worker, method):
    if method == 'play':
        return await worker.play(CHAT, 'new-source', title='new-title')
    if method == 'volume':
        return await worker.volume(CHAT, 120)
    return await getattr(worker, method)(CHAT)


@pytest.mark.parametrize('method', ['play', 'pause', 'resume', 'leave', 'volume'])
@pytest.mark.parametrize('failure', ['timeout', 'false', 'error'])
def test_failed_native_controls_keep_existing_state(monkeypatch, method, failure):
    async def scenario():
        worker = engine()
        if method == 'resume':
            worker.playbacks[CHAT].paused_at = time.time()
        original = worker.playbacks[CHAT]
        before = (original.paused_at, original.started_at, original.paused_total)
        call_name = {'leave': 'leave_call', 'volume': 'change_volume_call'}.get(method, method)
        target = getattr(worker._call, call_name)
        if failure == 'false':
            target.return_value = False
        elif failure == 'error':
            target.side_effect = RuntimeError('private-source secret')
        else:
            monkeypatch.setattr(voice, 'STOP_TIMEOUT', 0.01)
            monkeypatch.setattr(voice, 'START_TIMEOUT', 0.01)
            async def block(*args):
                await asyncio.Event().wait()
            target.side_effect = block
        with pytest.raises(voice.VoiceUnavailable) as error:
            await operate(worker, method)
        assert 'secret' not in str(error.value) and 'private-source' not in str(error.value)
        assert worker.playback(CHAT) is original
        assert (original.paused_at, original.started_at, original.paused_total) == before
    asyncio.run(scenario())


def test_acknowledged_leave_clears_only_this_chat():
    async def scenario():
        worker = engine()
        worker.playbacks[CHAT-1] = voice.Playback('other', 'other-source')
        await worker.leave(CHAT)
        assert worker.playback(CHAT) is None
        assert worker.playback(CHAT-1).title == 'other'
    asyncio.run(scenario())


@pytest.mark.parametrize('command', ['stop', 'leave', 'skip'])
def test_handlers_do_not_claim_leave_on_failure(tmp_path, monkeypatch, command):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        ctx.voice.leave = AsyncMock(side_effect=voice.VoiceUnavailable('secret-source'))
        response = await invoke(handlers, '/' + command)
        body = str(response.reply.await_args.args[0])
        assert 'not confirmed' in body
        assert 'secret-source' not in body
        assert 'left the voice chat' not in body.lower()
    asyncio.run(scenario())
