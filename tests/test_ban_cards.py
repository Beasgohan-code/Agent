"""Base ban/unban use shared targeting, live permissions and acknowledged rich results."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['ban','unban'])
async def test_ban_unban_username_and_rich_acknowledgement(tmp_path,command):
    ctx,client,message=setup(tmp_path,'/'+command+' @target'+(' spam <ads>' if command=='ban' else ''))
    method=AsyncMock(return_value=True)
    setattr(client,command+'_chat_member',method)
    await moderation.build(ctx)[1][command](client,message)
    method.assert_awaited_once_with(message.chat.id,22)
    client.get_users.assert_awaited_once_with('@target')
    text=str(message.replies[-1])
    assert 'Telegram confirmed' in text and 'Moderator' in text
    assert '<ads>' not in text
    assert ctx.chats.history(message.chat.id)[0]['action']==command


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['ban','unban'])
async def test_ban_false_ack_never_success_or_audit(tmp_path,command):
    ctx,client,message=setup(tmp_path,'/'+command+' 22')
    setattr(client,command+'_chat_member',AsyncMock(return_value=False))
    await moderation.build(ctx)[1][command](client,message)
    assert 'unconfirmed' in str(message.replies[-1]).lower()
    assert not ctx.chats.history(message.chat.id)


@pytest.mark.asyncio
async def test_ban_current_bot_rights_required(tmp_path):
    ctx,client,message=setup(tmp_path,'/ban 22')
    old=client.get_chat_member.side_effect
    async def member(chat,uid):
        if uid==99:
            return NS(status='member',privileges=None)
        return await old(chat,uid)
    client.get_chat_member=AsyncMock(side_effect=member)
    client.ban_chat_member=AsyncMock(return_value=True)
    await moderation.build(ctx)[1]['ban'](client,message)
    client.ban_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_ban_timeout_redacted_and_never_retried(tmp_path):
    ctx,client,message=setup(tmp_path,'/ban @target spam')
    client.ban_chat_member=AsyncMock(side_effect=TimeoutError('PRIVATE_TOKEN'))
    await moderation.build(ctx)[1]['ban'](client,message)
    client.ban_chat_member.assert_awaited_once()
    assert 'PRIVATE_TOKEN' not in str(message.replies)
    assert 'unconfirmed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_ban_final_caller_rights_loss_never_mutates(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/ban 22')
    client.ban_chat_member=AsyncMock(return_value=True)
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['ban'](client,message)
    client.ban_chat_member.assert_not_awaited()
    assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['ban', 'unban', 'kick', 'mute'])
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError])
async def test_confirmed_base_moderation_does_not_resend_after_card_failure(tmp_path, command, failure, caplog):
    ctx, client, message = setup(tmp_path, '/' + command + ' 22')
    from agent.platform.actions import ActionRouter
    ctx.actions = ActionRouter()
    client.ban_chat_member = AsyncMock(return_value=True)
    client.unban_chat_member = AsyncMock(return_value=True)
    message.reply = AsyncMock(side_effect=[failure('SECRET_DELIVERY_TEXT'), None])
    await moderation.build(ctx)[1][command](client, message)
    message.reply.assert_awaited_once()
    if command in ('ban', 'kick'):
        client.ban_chat_member.assert_awaited_once()
    else:
        client.ban_chat_member.assert_not_awaited()
    if command in ('unban', 'kick'):
        client.unban_chat_member.assert_awaited_once()
    else:
        client.unban_chat_member.assert_not_awaited()
    assert client.restrict_chat_member.await_count == (1 if command == 'mute' else 0)
    assert ctx.chats.history(message.chat.id)[0]['action'] == command
    assert 'SECRET_DELIVERY_TEXT' not in caplog.text
    if command == 'mute':
        assert not ctx._mute_undo_entries


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['ban', 'unban', 'kick', 'mute'])
async def test_confirmed_base_moderation_card_cancellation_propagates(tmp_path, command):
    import asyncio
    ctx, client, message = setup(tmp_path, '/' + command + ' 22')
    from agent.platform.actions import ActionRouter
    ctx.actions = ActionRouter()
    client.ban_chat_member = AsyncMock(return_value=True)
    client.unban_chat_member = AsyncMock(return_value=True)
    message.reply = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await moderation.build(ctx)[1][command](client, message)
    message.reply.assert_awaited_once()
    assert ctx.chats.history(message.chat.id)[0]['action'] == command
    if command == 'mute':
        assert not ctx._mute_undo_entries
