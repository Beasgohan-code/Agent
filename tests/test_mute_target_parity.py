"""Mute parses duration after the target, never from a numeric user ID."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from datetime import datetime,timezone
import pytest
import test_moderation as fixtures
from agent.modules import moderation


def setup(tmp_path,text):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    client.get_users=AsyncMock(return_value=NS(id=22))
    async def member(chat,uid):
        return fixtures.member(fixtures.MEMBER if uid==22 else fixtures.ADMIN)
    client.get_chat_member=AsyncMock(side_effect=member)
    client.restrict_chat_member=AsyncMock(return_value=True)
    return ctx,client,fixtures.FakeMessage(text)


@pytest.mark.asyncio
async def test_mute_id_then_duration_not_id_as_minutes(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 22 2m spam')
    await moderation.build(ctx)[1]['mute'](client,message)
    until=client.restrict_chat_member.await_args.kwargs['until_date']
    assert 115<(until-datetime.now(timezone.utc)).total_seconds()<=120
    assert '2m' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_mute_username_with_reason_defaults_safely(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute @target spam reason')
    await moderation.build(ctx)[1]['mute'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    assert '10m' in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('duration',['0s','59s','367d','999999999999999m','10x'])
async def test_mute_bad_duration_never_requests_restriction(tmp_path,duration):
    ctx,client,message=setup(tmp_path,'/mute 22 '+duration)
    await moderation.build(ctx)[1]['mute'](client,message)
    client.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_mute_false_ack_not_audited_or_reported_as_success(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 22 2m')
    client.restrict_chat_member=AsyncMock(return_value=False)
    await moderation.build(ctx)[1]['mute'](client,message)
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert not ctx.chats.history(message.chat.id)


@pytest.mark.asyncio
async def test_mute_reply_duration_and_permission_loss_before_mutation(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute 2m')
    message.reply_to_message=NS(chat=NS(id=message.chat.id),from_user=NS(id=22))
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['mute'](client,message)
    client.restrict_chat_member.assert_not_awaited()
    assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_mute_ambiguous_result_never_retried_or_leaked(tmp_path):
    ctx,client,message=setup(tmp_path,'/mute @target 2m')
    client.restrict_chat_member=AsyncMock(side_effect=TimeoutError('PRIVATE_TOKEN'))
    await moderation.build(ctx)[1]['mute'](client,message)
    client.restrict_chat_member.assert_awaited_once()
    assert 'PRIVATE_TOKEN' not in str(message.replies)
    assert 'unconfirmed' in str(message.replies[-1])
