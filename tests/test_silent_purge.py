"""Silent purge validates and authorizes before any irreversible request."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_moderation as fixtures
from agent.modules import moderation


def setup(tmp_path,text='/spurge 3'):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
    client.delete_messages=AsyncMock(side_effect=[3,1])
    message=fixtures.FakeMessage(text,message_id=100)
    return ctx,client,message


@pytest.mark.asyncio
async def test_spurge_success_deletes_bounded_range_then_command_without_card(tmp_path):
    ctx,client,message=setup(tmp_path)
    await moderation.build(ctx)[1]['spurge'](client,message)
    assert client.delete_messages.await_args_list[0].args==(message.chat.id,[99,98,97])
    assert client.delete_messages.await_args_list[1].args==(message.chat.id,100)
    assert message.replies==[]
    assert ctx.chats.history(message.chat.id)[0]['action']=='spurge'


@pytest.mark.asyncio
@pytest.mark.parametrize('arg',['0','-2','101','nope','2 extra','9'*1000])
async def test_spurge_invalid_count_never_deletes(tmp_path,arg):
    ctx,client,message=setup(tmp_path,'/spurge '+arg)
    await moderation.build(ctx)[1]['spurge'](client,message)
    client.delete_messages.assert_not_awaited()
    assert 'Usage' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_spurge_denied_caller_never_deletes(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    await moderation.build(ctx)[1]['spurge'](client,message)
    client.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_spurge_timeout_not_retried_and_keeps_command(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.delete_messages=AsyncMock(side_effect=TimeoutError('SECRET'))
    await moderation.build(ctx)[1]['spurge'](client,message)
    assert client.delete_messages.await_count==1
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_spurge_rechecks_caller_after_bot_rights(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['spurge'](client,message)
    client.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('ack',[None,False,True,0,-1])
async def test_spurge_unacknowledged_range_keeps_command(tmp_path,ack):
    ctx,client,message=setup(tmp_path)
    client.delete_messages=AsyncMock(return_value=ack)
    await moderation.build(ctx)[1]['spurge'](client,message)
    assert client.delete_messages.await_count==1
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert not ctx.chats.history(message.chat.id)


@pytest.mark.asyncio
async def test_spurge_bot_denied_before_deletion(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['spurge'](client,message)
    client.delete_messages.assert_not_awaited()
    assert 'bot needs' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_spurge_command_cleanup_failure_not_reported_as_range_failure(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.delete_messages=AsyncMock(side_effect=[1,TimeoutError('SECRET')])
    await moderation.build(ctx)[1]['spurge'](client,message)
    assert client.delete_messages.await_count==2
    assert 'command cleanup unconfirmed' in str(message.replies[-1])
    assert 'SECRET' not in str(message.replies[-1])
    assert ctx.chats.history(message.chat.id)[0]['action']=='spurge'
