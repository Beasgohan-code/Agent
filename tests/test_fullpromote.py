"""Full promotion is explicit group-owner delegation, never global-owner bypass."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group


def setup(tmp_path,text='/fullpromote 22 confirm'):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    client=fixtures.FakeClient()
    client.get_me=AsyncMock(return_value=NS(id=99))
    client.get_users=AsyncMock(return_value=NS(id=22))
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),owner])
    client.promote_chat_member=AsyncMock(return_value=True)
    return ctx,client,fixtures.FakeMessage(text)


@pytest.mark.asyncio
async def test_fullpromote_owner_grants_bot_ceiling_after_confirmation(tmp_path):
    ctx,client,message=setup(tmp_path)
    await group.build(ctx)[1]['fullpromote'](client,message)
    privileges=client.promote_chat_member.await_args.kwargs['privileges']
    assert privileges.can_promote_members is True
    assert privileges.can_delete_messages is True
    assert privileges.is_anonymous is False
    assert privileges.can_post_messages is False
    assert ctx.chats.history(message.chat.id)[0]['action']=='fullpromote'
    assert 'confirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_fullpromote_admin_including_global_owner_denied(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'group owner' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['/fullpromote 22','/fullpromote 22 yes','/fullpromote 22 confirm extra'])
async def test_fullpromote_needs_exact_confirmation(tmp_path,text):
    ctx,client,message=setup(tmp_path,text)
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'confirm' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_does_not_retry_unconfirmed_mutation(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.promote_chat_member=AsyncMock(side_effect=TimeoutError('SECRET'))
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert client.promote_chat_member.await_count==1
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert 'SECRET' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_bot_ceiling_and_final_ownership_recheck(tmp_path):
    ctx,client,message=setup(tmp_path)
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN,can_delete_messages=False)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),owner])
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert client.promote_chat_member.await_args.kwargs['privileges'].can_delete_messages is False
    ctx,client,message=setup(tmp_path)
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN)])
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    assert 'ownership changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_existing_admin_not_overwritten(tmp_path):
    ctx,client,message=setup(tmp_path)
    owner=fixtures.member(fixtures.OWNER)
    bot=fixtures.member(fixtures.ADMIN)
    bot.privileges.can_promote_members=True
    client.get_chat_member=AsyncMock(side_effect=[owner,bot,fixtures.member(fixtures.ADMIN)])
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.promote_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_fullpromote_false_ack_not_audited_as_success(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.promote_chat_member=AsyncMock(return_value=False)
    await group.build(ctx)[1]['fullpromote'](client,message)
    assert not ctx.chats.history(message.chat.id)
    assert 'unconfirmed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_fullpromote_same_chat_reply_requires_confirm(tmp_path):
    ctx,client,message=setup(tmp_path,'/fullpromote confirm')
    message.reply_to_message=NS(chat=NS(id=message.chat.id),from_user=NS(id=22))
    await group.build(ctx)[1]['fullpromote'](client,message)
    client.get_users.assert_not_awaited()
    client.promote_chat_member.assert_awaited_once()
