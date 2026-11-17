"""Optional promotion title is validated before mutation; partial results are explicit."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_group as fixtures
from agent.modules import group


def setup(tmp_path,text='/promote @target Team Lead'):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    rights=NS(can_promote_members=True,can_manage_chat=True,can_delete_messages=True)
    client=NS(get_me=AsyncMock(return_value=NS(id=99)),get_users=AsyncMock(return_value=NS(id=22)),
              promote_chat_member=AsyncMock(return_value=True),set_administrator_title=AsyncMock(return_value=True))
    async def member(chat,uid):
        return NS(status=fixtures.MEMBER if uid==22 else fixtures.ADMIN,privileges=rights,can_be_edited=True)
    client.get_chat_member=AsyncMock(side_effect=member)
    return ctx,client,fixtures.FakeMessage(text)


@pytest.mark.asyncio
async def test_promotion_title_explicit_target(tmp_path):
    ctx,client,message=setup(tmp_path)
    await group.build(ctx)[1]['promote'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    client.promote_chat_member.assert_awaited_once()
    client.set_administrator_title.assert_awaited_once_with(message.chat.id,22,'Team Lead')
    assert 'title confirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_promotion_title_reply_target(tmp_path):
    ctx,client,message=setup(tmp_path,'/promote Team Lead')
    message.reply_to_message=NS(chat=NS(id=message.chat.id),from_user=NS(id=22))
    await group.build(ctx)[1]['promote'](client,message)
    client.get_users.assert_not_awaited()
    client.set_administrator_title.assert_awaited_once_with(message.chat.id,22,'Team Lead')


@pytest.mark.asyncio
@pytest.mark.parametrize('title',['x'*17,'bad\nline','bad\x00title'])
async def test_promotion_title_invalid_before_promotion(tmp_path,title):
    ctx,client,message=setup(tmp_path,'/promote @target '+title)
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    client.set_administrator_title.assert_not_awaited()
    assert 'title' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_promotion_title_failure_is_partial_and_redacted(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.set_administrator_title=AsyncMock(side_effect=TimeoutError('SECRET'))
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    client.set_administrator_title.assert_awaited_once()
    text=str(message.replies[-1])
    assert 'Promotion confirmed' in text and 'title unconfirmed' in text
    assert 'SECRET' not in text


@pytest.mark.asyncio
async def test_promotion_unacknowledged_never_sets_title(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.promote_chat_member=AsyncMock(return_value=False)
    await group.build(ctx)[1]['promote'](client,message)
    client.set_administrator_title.assert_not_awaited()


@pytest.mark.asyncio
async def test_title_false_ack_is_partial_success(tmp_path):
    ctx,client,message=setup(tmp_path)
    client.set_administrator_title=AsyncMock(return_value=False)
    await group.build(ctx)[1]['promote'](client,message)
    assert 'Promotion confirmed' in str(message.replies[-1])
    assert 'title unconfirmed' in str(message.replies[-1])
    assert ctx.chats.history(message.chat.id)[0]['action']=='promote'


@pytest.mark.asyncio
async def test_reply_no_title_keeps_legacy_path(tmp_path):
    ctx,client,message=setup(tmp_path,'/promote')
    message.reply_to_message=NS(chat=NS(id=message.chat.id),from_user=NS(id=22))
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    client.set_administrator_title.assert_not_awaited()


@pytest.mark.asyncio
async def test_promotion_title_does_not_change_rights_parser(tmp_path):
    from agent.modules.group.admin import resolve
    ctx,client,message=setup(tmp_path,'/rights @target Team Lead')
    with pytest.raises(ValueError):
        await resolve(client,message)


@pytest.mark.asyncio
async def test_promotion_without_args_keeps_text_mention_target(tmp_path):
    ctx,client,message=setup(tmp_path,'/promote')
    message.entities=[NS(user=NS(id=22))]
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    client.get_users.assert_not_awaited()
