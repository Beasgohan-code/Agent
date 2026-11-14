"""Voice clients are optional, isolated and cleaned even on partial starts."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform import voice


@pytest.fixture
def clients(monkeypatch):
    client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(),
                             is_user_authorized=AsyncMock(return_value=True),
                             get_me=AsyncMock(return_value=SimpleNamespace(bot=False)))
    call = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(),
                           on_update=lambda _: lambda fn: fn)
    monkeypatch.setitem(sys.modules, 'telethon', SimpleNamespace(TelegramClient=lambda *a, **k: client))
    monkeypatch.setitem(sys.modules, 'telethon.sessions', SimpleNamespace(StringSession=lambda value: value))
    monkeypatch.setitem(sys.modules, 'pytgcalls', SimpleNamespace(PyTgCalls=lambda c: call, filters=SimpleNamespace(stream_end=lambda value: value)))
    monkeypatch.setitem(sys.modules, 'pytgcalls.types', SimpleNamespace(StreamEnded=SimpleNamespace(Type=SimpleNamespace(AUDIO='audio'))))
    return client, call


def engine():
    return voice.VoiceEngine(session_string='private-session', api_id=1, api_hash='private-api-hash')


def test_successful_voice_start_and_stop_are_idempotent(clients):
    async def scenario():
        client, call = clients
        worker = engine()
        await asyncio.gather(worker.start(), worker.start())
        assert worker.connected
        client.connect.assert_awaited_once()
        call.start.assert_awaited_once()
        await worker.shutdown()
        await worker.shutdown()
        client.disconnect.assert_awaited_once()
        call.stop.assert_awaited_once()
        assert not worker.connected
    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['connect', 'authorize', 'identity', 'call'])
def test_failed_start_cleans_partial_clients_and_sanitizes_error(clients, phase):
    async def scenario():
        client, call = clients
        failure = RuntimeError('private-session private-api-hash')
        target = {'connect': client.connect, 'authorize': client.is_user_authorized,
                  'identity': client.get_me, 'call': call.start}[phase]
        target.side_effect = failure
        worker = engine()
        with pytest.raises(voice.VoiceUnavailable) as error:
            await worker.start()
        assert 'private-session' not in str(error.value)
        assert not worker.connected
        assert worker._client is None and worker._call is None
        client.disconnect.assert_awaited_once()
        if phase == 'call':
            call.stop.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('authorized,identity', [(False, SimpleNamespace(bot=False)),
                                                 (True, SimpleNamespace(bot=True)), (True, None)])
def test_unauthorized_or_bot_assistant_is_refused(clients, authorized, identity):
    async def scenario():
        client, call = clients
        client.is_user_authorized.return_value = authorized
        client.get_me.return_value = identity
        with pytest.raises(voice.VoiceUnavailable):
            await engine().start()
        client.disconnect.assert_awaited_once()
        call.start.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_and_cancellation_release_assistant(clients, monkeypatch, cancel):
    async def scenario():
        client, _ = clients
        entered = asyncio.Event()
        async def blocked():
            entered.set()
            await asyncio.Event().wait()
        client.connect.side_effect = blocked
        monkeypatch.setattr(voice, 'START_TIMEOUT', 0.02 if not cancel else 30)
        worker = engine()
        task = asyncio.create_task(worker.start())
        await entered.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else voice.VoiceUnavailable):
            await task
        client.disconnect.assert_awaited_once()
        assert not worker.connected
    asyncio.run(scenario())


def test_wedged_call_shutdown_still_disconnects_telegram(clients, monkeypatch):
    async def scenario():
        client, call = clients
        async def blocked():
            await asyncio.Event().wait()
        worker = engine()
        await worker.start()
        call.stop.side_effect = blocked
        monkeypatch.setattr(voice, 'STOP_TIMEOUT', 0.01)
        await worker.shutdown()
        client.disconnect.assert_awaited_once()
    asyncio.run(scenario())


def test_voice_uses_verified_account_for_guard_and_releases_it(clients):
    async def scenario():
        client, _ = clients
        client.get_me.return_value = SimpleNamespace(bot=False, id=456)
        guard = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock(),
                                watch=lambda callback: None, held=True)
        worker = voice.VoiceEngine(session_string='private-session', api_id=1,
                                   api_hash='hash', assistant_lease=guard)
        await worker.start()
        guard.acquire.assert_awaited_once_with(456)
        guard.held = False
        with pytest.raises(voice.VoiceUnavailable):
            worker._require()
        await worker.shutdown()
        guard.release.assert_awaited_once()
    asyncio.run(scenario())


def test_busy_account_never_starts_voice_call(clients):
    async def scenario():
        client, call = clients
        client.get_me.return_value = SimpleNamespace(bot=False, id=456)
        guard = SimpleNamespace(acquire=AsyncMock(side_effect=RuntimeError('busy')),
                                release=AsyncMock(), held=False)
        worker = voice.VoiceEngine(session_string='private-session', api_id=1,
                                   api_hash='hash', assistant_lease=guard)
        with pytest.raises(voice.VoiceUnavailable):
            await worker.start()
        call.start.assert_not_awaited()
        client.disconnect.assert_awaited_once()
        guard.release.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('method', ['pause', 'resume', 'volume'])
def test_unacknowledged_controls_never_update_playback_state(clients, method):
    async def scenario():
        _, call = clients
        worker = engine()
        await worker.start()
        playback = voice.Playback('track', 'source', paused_at=123 if method == 'resume' else None)
        worker.playbacks[1] = playback
        before = playback.paused_at
        setattr(call, 'change_volume_call' if method == 'volume' else method, AsyncMock(return_value=False))
        with pytest.raises(voice.VoiceUnavailable):
            if method == 'volume':
                await worker.volume(1, 120)
            else:
                await getattr(worker, method)(1)
        assert playback.paused_at == before
        await worker.shutdown()
    asyncio.run(scenario())
