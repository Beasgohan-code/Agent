"""Private rules deliver canonical group rules only to the verified requesting member."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group
from agent.platform.group_rules import save_rules


def setup(tmp_path):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.send_message=AsyncMock(return_value=NS(id=1))
    message=fixtures.FakeMessage('/privaterules')
    return ctx,client,message


@pytest.mark.asyncio
async def test_private_rules_dm_only_and_escaped(tmp_path):
    ctx,client,message=setup(tmp_path)
    await save_rules(ctx,message.chat.id,'<no ads>',actor=11)
    await group.build(ctx)[1]['privaterules'](client,message)
    client.send_message.assert_awaited_once()
    call=client.send_message.await_args
    assert call.kwargs['chat_id']==message.from_user.id
    assert '&lt;no ads&gt;' in call.kwargs['text']
    assert '<no ads>' not in call.kwargs['text']
    assert 'delivered' in str(message.replies[-1]).lower()
    assert 'no ads' not in str(message.replies)


@pytest.mark.asyncio
async def test_private_rules_blocked_dm_never_falls_back_to_group(tmp_path):
    ctx,client,message=setup(tmp_path)
    await save_rules(ctx,message.chat.id,'PRIVATE_RULE_BODY',actor=11)
    client.send_message=AsyncMock(side_effect=RuntimeError('SECRET'))
    await group.build(ctx)[1]['privaterules'](client,message)
    text=str(message.replies)
    assert 'PRIVATE_RULE_BODY' not in text and 'SECRET' not in text
    assert 'unconfirmed' in text.lower() and 'start' in text.lower()
    client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_rules_denies_unverified_member(tmp_path):
    from pyrogram.enums import ChatMemberStatus
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.LEFT))
    await group.build(ctx)[1]['privaterules'](client,message)
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_rules_rejects_arguments_and_reports_empty_rules(tmp_path):
    ctx,client,message=setup(tmp_path)
    handler=group.build(ctx)[1]['privaterules']
    message.text='/privaterules -200'
    await handler(client,message)
    assert 'Usage' in str(message.replies[-1])
    message.text='/privaterules'
    await handler(client,message)
    assert 'no rules' in str(message.replies[-1]).lower()
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_rules_partial_delivery_never_restarts_send(tmp_path):
    ctx,client,message=setup(tmp_path)
    await save_rules(ctx,message.chat.id,'😀'*2000,actor=11)
    client.send_message=AsyncMock(side_effect=[NS(id=1),TimeoutError('SECRET')])
    await group.build(ctx)[1]['privaterules'](client,message)
    assert client.send_message.await_count==2
    assert '1 parts acknowledged' in str(message.replies[-1])
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_private_rules_rejects_anonymous_sender(tmp_path):
    ctx,client,message=setup(tmp_path)
    message.sender_chat=NS(id=message.chat.id)
    await group.build(ctx)[1]['privaterules'](client,message)
    client.send_message.assert_not_awaited()
