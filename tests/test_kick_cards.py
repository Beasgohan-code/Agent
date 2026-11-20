"""Kick success needs both acknowledgements; partial failures retain recovery guidance."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
async def test_kick_username_rich_card_only_after_both_steps(tmp_path):
    ctx,client,message=setup(tmp_path,'/kick @target spam <ads>')
    client.ban_chat_member=AsyncMock(return_value=True)
    client.unban_chat_member=AsyncMock(return_value=True)
    await moderation.build(ctx)[1]['kick'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    client.ban_chat_member.assert_awaited_once_with(message.chat.id,22)
    client.unban_chat_member.assert_awaited_once_with(message.chat.id,22)
    text=str(message.replies[-1])
    assert 'Member kicked' in text and 'Telegram confirmed' in text
    assert 'Moderator' in text and '&lt;ads&gt;' in text
    assert '<ads>' not in text


@pytest.mark.asyncio
async def test_kick_false_ban_never_attempts_unban_or_success_audit(tmp_path):
    ctx,client,message=setup(tmp_path,'/kick 22')
    client.ban_chat_member=AsyncMock(return_value=False)
    client.unban_chat_member=AsyncMock(return_value=True)
    await moderation.build(ctx)[1]['kick'](client,message)
    client.unban_chat_member.assert_not_awaited()
    assert not ctx.chats.history(message.chat.id)
    assert 'unconfirmed' in str(message.replies[-1]).lower()


@pytest.mark.asyncio
async def test_kick_unban_timeout_reports_partial_without_retry(tmp_path):
    ctx,client,message=setup(tmp_path,'/kick 22')
    client.ban_chat_member=AsyncMock(return_value=True)
    client.unban_chat_member=AsyncMock(side_effect=TimeoutError('PRIVATE_TOKEN'))
    await moderation.build(ctx)[1]['kick'](client,message)
    client.ban_chat_member.assert_awaited_once()
    client.unban_chat_member.assert_awaited_once()
    text=str(message.replies[-1])
    assert 'Kick incomplete' in text and '/unban 22' in text and 'may still be banned' in text
    assert 'PRIVATE_TOKEN' not in text
    assert ctx.chats.history(message.chat.id)[0]['action']=='kick:incomplete'


@pytest.mark.asyncio
async def test_kick_bot_rights_denial_before_mutation(tmp_path):
    ctx,client,message=setup(tmp_path,'/kick 22')
    old=client.get_chat_member.side_effect
    async def membership(chat,uid):
        return NS(status='member',privileges=None) if uid==99 else await old(chat,uid)
    client.get_chat_member=AsyncMock(side_effect=membership)
    client.ban_chat_member=AsyncMock(return_value=True)
    await moderation.build(ctx)[1]['kick'](client,message)
    client.ban_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_kick_audit_failure_keeps_recovery_guidance(tmp_path):
    from unittest.mock import Mock
    ctx,client,message=setup(tmp_path,'/kick 22')
    client.ban_chat_member=AsyncMock(return_value=True)
    client.unban_chat_member=AsyncMock(return_value=False)
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_DB'))
    await moderation.build(ctx)[1]['kick'](client,message)
    text=str(message.replies[-1])
    assert 'Kick incomplete' in text and '/unban 22' in text
    assert 'audit unconfirmed' in text and 'PRIVATE_DB' not in text
    client.ban_chat_member.assert_awaited_once()
    client.unban_chat_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_kick_final_permission_loss_before_any_side_effect(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/kick 22')
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    client.ban_chat_member=AsyncMock(return_value=True)
    await moderation.build(ctx)[1]['kick'](client,message)
    client.ban_chat_member.assert_not_awaited()
    assert 'changed' in str(message.replies[-1])
