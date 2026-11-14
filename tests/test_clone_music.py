"""Music onboarding never asks for credentials before consent/readiness."""
import asyncio
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules.clone import setup as wizard_module
from agent.modules.clone.assistant import validate_session
from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneError
from agent.platform.secrets import SecretBox, SecretError
from test_clone import build, FakeBot, FakeMessage, TOKEN_A, MEMBER
from test_clone_setup import identity_step, query

SESSION = '1' + 'a' * 352


def ready(ctx, monkeypatch):
    ctx.settings = replace(ctx.settings, database_url='postgresql://test')
    ctx.clones._settings = ctx.settings
    ctx.db = SimpleNamespace(connected=True)
    monkeypatch.setattr(wizard_module, 'capability', lambda session: (True, ''))


def parser(monkeypatch, **overrides):
    values = dict(server_address='149.154.167.51', dc_id=2, port=443, auth_key=object())
    values.update(overrides)
    monkeypatch.setitem(sys.modules, 'telethon.sessions', SimpleNamespace(StringSession=lambda value: SimpleNamespace(**values)))


def test_music_session_flow_requires_consent_and_encrypts_credentials(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ready(ctx, monkeypatch)
        parser(monkeypatch)
        class MusicBot(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock(), connected=True)
        ctx.clones._factory = MusicBot
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':music')
        assert state.step == 'music_consent'
        await wizard.receive(None, FakeMessage(SESSION))
        assert state.assistant_session == ''
        await wizard.press(None, query(state), state.nonce + ':music_consent')
        request = FakeMessage(SESSION)
        request.delete = AsyncMock()
        await wizard.receive(None, request)
        request.delete.assert_awaited_once()
        assert state.step == 'log'
        assert SESSION not in repr(state)
        await wizard.receive(None, FakeMessage('skip'))
        await wizard.press(None, query(state), state.nonce + ':create')
        record = wizard.store.all()[0]
        assert record.selected_plugins == ('music',)
        assert record.assistant_session == SESSION
        assert SESSION not in repr(record)
        settings = ctx.clones.settings_for(record)
        assert settings.session_string == SESSION
        assert settings.owner_id == MEMBER
        assert settings.ai_api_key is None
        raw = wizard.store.path.read_text()
        assert SESSION not in raw and 'assistant_session_enc' in raw
        restored = CloneStore(wizard.store.path.parent, box=wizard.store._box)
        assert restored.get(record.bot_id).assistant_session == SESSION
        assert not state.assistant_session and not state.token
    asyncio.run(scenario())


@pytest.mark.parametrize('reason', ['database', 'dependencies'])
def test_music_readiness_failure_does_not_prompt_for_session(tmp_path, monkeypatch, reason):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ready(ctx, monkeypatch)
        if reason == 'database':
            ctx.db.connected = False
        else:
            monkeypatch.setattr(wizard_module, 'capability', lambda session: (False, 'missing'))
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':music')
        assert state.step == 'plugin' and state.assistant_session == ''
    asyncio.run(scenario())


@pytest.mark.parametrize('values', [{'server_address': '127.0.0.1'}, {'server_address': '10.0.0.1'},
                                    {'server_address': '169.254.169.254'}, {'port': 80},
                                    {'dc_id': 99}, {'auth_key': None}])
def test_session_endpoint_validation_refuses_untrusted_targets(monkeypatch, values):
    parser(monkeypatch, **values)
    with pytest.raises(ValueError):
        validate_session(SESSION)


@pytest.mark.parametrize('value', ['123456', '+919999999999', 'password', '1' + 'a' * 10000], ids=['otp', 'phone', 'password', 'oversize'])
def test_session_shape_rejects_otp_phone_password_and_oversized_input(value):
    with pytest.raises(ValueError):
        validate_session(value)


def test_music_session_is_never_written_as_plaintext(tmp_path):
    store = CloneStore(tmp_path, box=SecretBox(None))
    with pytest.raises(SecretError):
        store.add(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
                        assistant_session=SESSION))
    assert not store.all()


def test_music_settings_fail_without_private_session_or_postgres(tmp_path):
    ctx, _, _ = build(tmp_path)
    record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, selected_plugins=('music',))
    with pytest.raises(CloneError, match='PostgreSQL'):
        ctx.clones.settings_for(record)


@pytest.mark.parametrize('finish', ['cancel', 'expire'])
def test_music_draft_secrets_clear_on_cancel_or_expiry(tmp_path, monkeypatch, finish):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ready(ctx, monkeypatch)
        parser(monkeypatch)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':music')
        await wizard.press(None, query(state), state.nonce + ':music_consent')
        await wizard.receive(None, FakeMessage(SESSION))
        assert state.assistant_session
        if finish == 'cancel':
            wizard.cancel(MEMBER)
        else:
            state.expires = 0
            wizard.active(MEMBER)
        assert not state.assistant_session and not state.token
        assert not wizard.store.all()
    asyncio.run(scenario())


def test_real_telethon_session_parser_is_offline_and_endpoint_restricted():
    sessions = pytest.importorskip('telethon.sessions')
    from telethon.crypto import AuthKey
    session = sessions.StringSession()
    session.set_dc(2, '149.154.167.51', 443)
    session.auth_key = AuthKey(bytes(range(256)))
    encoded = session.save()
    assert validate_session(encoded) == encoded
    session.set_dc(2, '127.0.0.1', 443)
    with pytest.raises(ValueError):
        validate_session(session.save())


def test_music_startup_failure_removes_encrypted_record_and_draft(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ready(ctx, monkeypatch)
        parser(monkeypatch)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':music')
        await wizard.press(None, query(state), state.nonce + ':music_consent')
        await wizard.receive(None, FakeMessage(SESSION))
        await wizard.receive(None, FakeMessage('skip'))
        wizard.manager.start = AsyncMock(side_effect=RuntimeError(SESSION))
        press = query(state)
        await wizard.press(None, press, state.nonce + ':create')
        assert not wizard.store.all()
        assert not state.assistant_session and not state.token
        assert SESSION not in str(press.message.replies)
    asyncio.run(scenario())


def test_settings_repr_contains_no_runtime_credentials(tmp_path):
    ctx, _, _ = build(tmp_path)
    settings = replace(ctx.settings, session_string=SESSION, ai_api_key='secret-ai-key',
                       database_url='postgresql://secret-db', link_secret='secret-signing-key')
    text = repr(settings)
    for secret in (SESSION, settings.bot_token, settings.api_hash, settings.token_key,
                   settings.database_url, settings.ai_api_key, settings.link_secret):
        assert secret not in text
