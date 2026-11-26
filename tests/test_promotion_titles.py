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
async def test_promotion_without_title_keeps_text_mention_target(tmp_path):
    ctx,client,message=setup(tmp_path,'/promote Alice')
    message.entities=[NS(user=NS(id=22),offset=9,length=5)]
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    client.get_users.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['promote','demote'])
@pytest.mark.parametrize('failure',['lookup','mutation'])
async def test_admin_change_provider_valueerror_never_reaches_reply(tmp_path,command,failure):
    ctx,client,message=setup(tmp_path,f'/{command} @target')
    original=client.get_chat_member.side_effect
    async def member(chat,uid):
        record=await original(chat,uid)
        if uid==22 and command=='demote':record.status=fixtures.ADMIN
        return record
    client.get_chat_member=AsyncMock(side_effect=member)
    if failure=='lookup':client.get_users.side_effect=ValueError('PRIVATE_PROVIDER_DATA')
    else:client.promote_chat_member.side_effect=ValueError('PRIVATE_PROVIDER_DATA')
    await group.build(ctx)[1][command](client,message)
    assert 'PRIVATE_PROVIDER_DATA' not in str(message.replies)
    assert 'unconfirmed' in str(message.replies[-1]).lower() or 'could not be confirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_demote_rejects_cross_chat_reply_and_invalid_targets(tmp_path):
    ctx,client,message=setup(tmp_path,'/demote')
    message.reply_to_message=NS(chat=NS(id=-999),from_user=NS(id=22))
    await group.build(ctx)[1]['demote'](client,message)
    client.promote_chat_member.assert_not_awaited()
    client.get_users.assert_not_awaited()
    for target in ('0',str(2**63),'@bad!','@'):
        ctx,client,message=setup(tmp_path,'/demote '+target)
        await group.build(ctx)[1]['demote'](client,message)
        client.get_users.assert_not_awaited()
        client.promote_chat_member.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['promote','demote'])
async def test_admin_changes_refuse_bot_or_oversized_caller(tmp_path,command):
    for user in (NS(id=11,is_bot=True),NS(id=2**63)):
        ctx,client,message=setup(tmp_path,f'/{command} @target')
        message.from_user=user
        await group.build(ctx)[1][command](client,message)
        client.get_users.assert_not_awaited()
        client.promote_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_promotion_caps_rights_using_final_caller_snapshot(tmp_path):
    ctx,client,message=setup(tmp_path,'/promote @target')
    checks=0
    async def member(chat,uid):
        nonlocal checks
        if uid==11:checks+=1
        rights=NS(can_promote_members=True,can_manage_chat=True,
                  can_delete_messages=not(uid==11 and checks>=3))
        return NS(status=fixtures.MEMBER if uid==22 else fixtures.ADMIN,privileges=rights,can_be_edited=True)
    client.get_chat_member=AsyncMock(side_effect=member)
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    assert client.promote_chat_member.call_args.kwargs['privileges'].can_delete_messages is False


@pytest.mark.asyncio
async def test_acknowledged_promotion_is_not_reported_failed_when_reply_fails(tmp_path,monkeypatch):
    import agent.modules.group.admin as implementation
    ctx,client,message=setup(tmp_path,'/promote @target')
    replies=AsyncMock(side_effect=[TimeoutError('PRIVATE_REPLY_DATA'),None])
    monkeypatch.setattr(implementation,'reply',replies)
    await group.build(ctx)[1]['promote'](client,message)
    client.promote_chat_member.assert_awaited_once()
    assert 'Administrator change confirmed' in replies.await_args_list[-1].args[1]
    assert 'PRIVATE_REPLY_DATA' not in str(replies.await_args_list[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['promote', 'demote'])
async def test_admin_change_rejects_a_mention_on_the_command_itself(tmp_path, command):
    ctx, client, message = setup(tmp_path, f'/{command} @target')
    message.entities = [NS(user=NS(id=22), offset=0, length=len(command) + 1)]
    await group.build(ctx)[1][command](client, message)
    client.promote_chat_member.assert_not_awaited()
    client.set_administrator_title.assert_not_awaited()
    client.get_users.assert_not_awaited()
