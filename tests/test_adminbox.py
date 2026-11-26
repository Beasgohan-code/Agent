"""Admin dashboard is read-only, live-authorized and advertises registered tools only."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group


@pytest.mark.asyncio
async def test_adminbox_live_permissions_and_registered_inventory(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    ctx.registry=NS(active_commands=lambda:('rights','ban','adminbox'))
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    message=fixtures.FakeMessage('/adminbox')
    await group.build(ctx)[1]['adminbox'](client,message)
    text=str(message.replies[-1])
    assert '/rights' in text and '/ban' in text
    assert '/tpromote' not in text and '/setchatname' not in text
    assert 'can_change_info' in text and 'Bot' in text and 'Caller' in text


@pytest.mark.asyncio
async def test_adminbox_denial_before_bot_lookup(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient(caller=fixtures.MEMBER)
    client.get_me=AsyncMock()
    message=fixtures.FakeMessage('/adminbox')
    await group.build(ctx)[1]['adminbox'](client,message)
    client.get_me.assert_not_awaited()
    assert 'permission' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_adminbox_arguments_rejected(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    message=fixtures.FakeMessage('/adminbox -200')
    await group.build(ctx)[1]['adminbox'](client,message)
    assert 'Usage' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_adminbox_api_failure_redacted(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(side_effect=RuntimeError('SECRET'))
    message=fixtures.FakeMessage('/adminbox')
    await group.build(ctx)[1]['adminbox'](client,message)
    assert 'unavailable' in str(message.replies[-1]).lower()
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_adminbox_rechecks_current_caller_before_render(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.MEMBER)])
    message=fixtures.FakeMessage('/adminbox')
    await group.build(ctx)[1]['adminbox'](client,message)
    assert 'changed' in str(message.replies[-1])
    assert 'Group admin dashboard' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_adminbox_missing_registry_is_explicit(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    ctx.registry=None
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    message=fixtures.FakeMessage('/adminbox')
    await group.build(ctx)[1]['adminbox'](client,message)
    text=str(message.replies[-1])
    assert 'inventory unavailable' in text
    assert '/promote' not in text
    assert client.calls==[]
