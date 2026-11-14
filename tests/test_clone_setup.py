"""Guided creation never persists unverified tokens or accepts other users' buttons."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_clone import build, FakeMessage, FakePremium, TOKEN_A, MEMBER
from agent.platform.roles import SudoStore


def query(state, user=MEMBER):
    message = FakeMessage('', uid=user)
    message.edit_text = AsyncMock()
    return SimpleNamespace(from_user=SimpleNamespace(id=user), message=message, answer=AsyncMock())


async def api(token, method, **values):
    if method == 'getMe':
        return {'id': 111111111, 'is_bot': True, 'username': 'verified_bot'}
    if method == 'getChat':
        return {'id': values['chat_id'], 'type': 'channel'}
    if method == 'getChatMember':
        return {'status': 'administrator', 'can_post_messages': True}
    raise AssertionError(method)


async def identity_step(ctx):
    wizard = ctx.clone_setup
    wizard.api = AsyncMock(side_effect=api)
    await wizard.begin(FakeMessage('/clone'))
    await wizard.receive(None, FakeMessage(TOKEN_A))
    return wizard, wizard.active(MEMBER)


def test_guided_filestore_setup_validates_and_configures_owned_clone(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        assert state.step == 'plugin'
        assert not ctx.clones.current()
        await wizard.press(None, query(state), state.nonce + ':files')
        await wizard.receive(None, FakeMessage('-100100'))
        assert state.step == 'storage'
        await wizard.receive(None, FakeMessage('-100200'))
        assert state.step == 'confirm'
        await wizard.press(None, query(state), state.nonce + ':create')
        record = ctx.clones.current()[0]
        assert record.owner_id == MEMBER
        assert record.selected_plugins == ('filestore',)
        assert record.log_channel == -100100
        assert record.storage_channel == -100200
        settings = ctx.clones.settings_for(record)
        assert settings.owner_id == MEMBER
        assert settings.bot_id == record.bot_id
        assert settings.link_secret != ctx.settings.link_secret
        assert settings.session_string is None
        assert settings.plugins == ('filestore',)
        assert settings.storage_channel == -100200
        assert wizard.active(MEMBER) is None
        assert TOKEN_A not in (tmp_path / 'data' / 'clones.json').read_text()
        persisted = json.loads((tmp_path / 'data' / 'clones.json').read_text())
        assert persisted[0]['managed_owner'] is True
    asyncio.run(scenario())


def test_telegram_identity_must_match_token_and_be_bot(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.api = AsyncMock(return_value={'id': 999, 'is_bot': False})
        await wizard.begin(FakeMessage('/clone'))
        await wizard.receive(None, FakeMessage(TOKEN_A))
        assert wizard.active(MEMBER).step == 'token'
        assert wizard.active(MEMBER).token == ''
        assert not ctx.clones.current()
    asyncio.run(scenario())


def test_wrong_user_cannot_advance_or_cancel_setup(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        press = query(state, 999)
        await wizard.press(None, press, state.nonce + ':files')
        assert state.step == 'plugin'
        assert press.answer.await_args.kwargs['show_alert']
    asyncio.run(scenario())


def test_expired_setup_refuses_buttons(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        state.expires = time.monotonic() - 1
        await wizard.press(None, query(state), state.nonce + ':files')
        assert wizard.active(MEMBER) is None
        assert not ctx.clones.current()
    asyncio.run(scenario())


def test_channel_requires_both_operator_and_clone_admin_rights(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':files')
        async def forbidden(token, method, **values):
            if method == 'getChatMember':
                return {'status': 'member'}
            return await api(token, method, **values)
        wizard.api = AsyncMock(side_effect=forbidden)
        await wizard.receive(None, FakeMessage('-100100'))
        assert state.step == 'log'
        assert state.log_channel is None
        assert not ctx.clones.current()
    asyncio.run(scenario())


def test_no_secrets_requested_without_encryption(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.store._box = SimpleNamespace(enabled=False)
        message = FakeMessage('/clone')
        await wizard.begin(message)
        assert wizard.active(MEMBER) is None
        assert 'TOKEN_KEY' in message.replies[0]
    asyncio.run(scenario())


def test_free_member_denied_sudo_grant_enables_setup(tmp_path):
    async def scenario():
        ctx, _, commands = build(tmp_path, premium=FakePremium())
        denied = FakeMessage('/clone')
        await commands['clone'](None, denied)
        assert ctx.clone_setup.active(MEMBER) is None
        ctx.sudo.change(11, MEMBER, add=True)
        await commands['clone'](None, FakeMessage('/clone'))
        assert ctx.clone_setup.active(MEMBER).step == 'token'
    asyncio.run(scenario())


def test_sudo_cannot_grant_itself_owner_privileges(tmp_path):
    store = SudoStore(tmp_path, owner_id=11)
    store.change(11, 22, add=True)
    assert SudoStore(tmp_path, owner_id=11).contains(22)
    with pytest.raises(PermissionError):
        store.change(22, 33, add=True)
    store.change(11, 22, add=False)
    assert not store.contains(22)


def test_group_command_never_starts_credential_collection(tmp_path):
    async def scenario():
        ctx, _, commands = build(tmp_path)
        message = FakeMessage('/clone ' + TOKEN_A)
        message.chat.id = -100
        await commands['clone'](None, message)
        assert not ctx.clones.current()
        assert ctx.clone_setup.active(MEMBER) is None
        assert TOKEN_A not in message.replies[0]
    asyncio.run(scenario())


def test_clone_does_not_inherit_parent_credentials_or_recursive_cloning(tmp_path):
    from dataclasses import replace
    from agent.modules.clone.store import Clone
    ctx, _, _ = build(tmp_path)
    ctx.clones._settings = replace(ctx.settings, session_string='PARENT_PRIVATE_SESSION',
                                   log_channel=-100111, storage_channel=-100222, plugins=('*',), health_port=8080)
    settings = ctx.clones.settings_for(Clone(bot_id=111111111, owner_id=22, token=TOKEN_A))
    assert settings.session_string is None
    assert settings.log_channel is None
    assert settings.storage_channel is None
    assert settings.health_port is None
    assert 'clone' not in settings.plugins
    assert '*' not in settings.plugins


def test_premium_loss_stops_running_clone_on_supervisor_pass(tmp_path):
    async def scenario():
        ledger = FakePremium({MEMBER})
        ctx, _, commands = build(tmp_path, premium=ledger)
        await commands['clone'](None, FakeMessage('/clone ' + TOKEN_A))
        ledger.ids.clear()
        await ctx.clones.supervise()
        assert not ctx.clones.running()
        assert ctx.clones.record(111111111).disabled
    asyncio.run(scenario())


def test_revoked_token_at_confirmation_does_not_create_clone(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':files')
        await wizard.receive(None, FakeMessage('skip'))
        await wizard.receive(None, FakeMessage('-100200'))
        wizard.api = AsyncMock(return_value={'id': 999, 'is_bot': True})
        final = query(state)
        await wizard.press(None, final, state.nonce + ':create')
        assert not ctx.clones.current()
        assert wizard.active(MEMBER) is None
        assert all(TOKEN_A not in body for body in final.message.replies)
    asyncio.run(scenario())


def test_clone_record_cannot_be_overwritten_by_another_owner(tmp_path):
    from agent.modules.clone.store import CloneStore, Clone
    store = CloneStore(tmp_path)
    store.add(Clone(bot_id=111111111, owner_id=22, token=TOKEN_A))
    with pytest.raises(ValueError, match='ownership cannot be overwritten'):
        store.add(Clone(bot_id=111111111, owner_id=33, token=TOKEN_A))
    assert store.get(111111111).owner_id == 22


def test_setup_secret_is_excluded_from_representation(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        assert TOKEN_A not in repr(state)
        assert TOKEN_A not in repr(wizard.sessions)
        wizard.cancel(MEMBER)
        assert not wizard.sessions
    asyncio.run(scenario())
