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
