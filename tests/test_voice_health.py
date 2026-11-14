"""Credential-safe cached voice reporting; no Telegram or streaming calls."""
import asyncio
from types import SimpleNamespace

from test_music_controls import wire, invoke
from test_player_card import CHAT, OWNER, STRANGER
from agent.platform.voice import VoiceEngine, Playback
from agent.modules.music.queue import QueueBook


def test_engine_diagnostics_are_allowlisted_and_group_local():
    engine = VoiceEngine(session_string='SECRET_SESSION', api_id=123, api_hash='SECRET_HASH')
    assert engine.diagnostics(CHAT) == dict(engine_ready=False, assistant_lease='not configured', playback='idle')
    engine._connected = True
    engine._call = object()
    engine.playbacks[CHAT] = Playback('SECRET_TITLE', 'SECRET_SOURCE', requested_by=123456)
    engine.playbacks[CHAT - 1] = Playback('OTHER_GROUP', 'OTHER_SECRET')
    assert engine.diagnostics(CHAT)['playback'] == 'playing'
    assert engine.diagnostics(CHAT - 2)['playback'] == 'idle'
    engine.playbacks[CHAT].paused_at = engine.playbacks[CHAT].started_at
    assert engine.diagnostics(CHAT)['playback'] == 'paused'
    engine._assistant_lease = SimpleNamespace(held=False)
    assert engine.diagnostics(CHAT)['engine_ready'] is False
    engine._assistant_lease.held = True
    assert engine.diagnostics(CHAT)['engine_ready'] is True
    text = str(engine.diagnostics(CHAT))
    assert 'SECRET' not in text and '123456' not in text and 'OTHER_GROUP' not in text


def test_peek_does_not_allocate_queue():
    queues = QueueBook()
    assert queues.peek(CHAT) is None
    assert queues.chats() == []


def test_voicehealth_permissions_args_privacy_and_no_mutation(tmp_path, monkeypatch):
    async def scenario():
        ctx, manifest, handlers = wire(tmp_path, monkeypatch)
        assert 'voicehealth' in manifest.commands
        ctx.voice.diagnostics = lambda chat: dict(engine_ready=True, assistant_lease='held', playback='playing',
                                                 source='SECRET_SOURCE', session='SECRET_SESSION')
        denied = await invoke(handlers, '/voicehealth', uid=STRANGER)
        assert 'administrators' in str(denied.reply.await_args.args[0])
        invalid = await invoke(handlers, '/voicehealth x')
        assert 'without arguments' in str(invalid.reply.await_args.args[0])
        report = await invoke(handlers, '/voicehealth', uid=OWNER)
        body = str(report.reply.await_args.args[0])
        assert 'Voice health' in body
        assert '<tg-emoji' in body and 'SECRET' not in body
        assert 'Not a live connectivity' in body
        assert not ctx.voice.play.await_count
        await invoke(handlers, '/play first')
        await invoke(handlers, '/play second')
        await invoke(handlers, '/volume 140')
        report = await invoke(handlers, '/voicehealth')
        body = str(report.reply.await_args.args[0])
        assert '140% acknowledged' in body
        assert 'first' not in body and 'second' not in body
        other = await invoke(handlers, '/voicehealth', chat=CHAT - 1)
        assert '140%' not in str(other.reply.await_args.args[0])
        ctx.voice.play.assert_awaited_once()
    asyncio.run(scenario())


def test_disconnected_ui_does_not_claim_ready(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        ctx.voice.diagnostics = lambda chat: dict(engine_ready=False, assistant_lease='not held', playback='idle')
        response = await invoke(handlers, '/voicehealth')
        assert 'not ready' in str(response.reply.await_args.args[0])
        assert 'Engine unavailable' in str(response.reply.await_args.args[0])
    asyncio.run(scenario())


def test_voicehealth_uses_native_rich_delivery(tmp_path, monkeypatch):
    from test_music_controls import message
    from test_player_card import FakeClient
    from unittest.mock import AsyncMock
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        ctx.voice.diagnostics = lambda chat: dict(engine_ready=True, assistant_lease='held', playback='idle')
        request = message('/voicehealth')
        request.id = 1
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await handlers['voicehealth'](FakeClient(), request)
        payload = request._client.send_rich_message.await_args.kwargs['rich_text'].html
        assert '<table' in payload and '<tg-emoji' in payload
        assert 'Voice health' in payload
        request.reply.assert_not_awaited()
    asyncio.run(scenario())
