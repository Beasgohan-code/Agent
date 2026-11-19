"""Warning-removal results distinguish durable changes from audit/report failures."""
from unittest.mock import AsyncMock,Mock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['unwarn','rmwarn','resetwarn','resetwarns'])
async def test_removal_username_rich_card_preserves_history(tmp_path,command):
    ctx,client,message=setup(tmp_path,'/'+command+' @target')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    from agent.modules import group
    module=group if command=='resetwarns' else moderation
    await module.build(ctx)[1][command](client,message)
    client.get_users.assert_awaited_once_with('@target')
    text=str(message.replies[-1])
    assert 'Warnings cleared' in text and 'Moderator' in text and 'History retained' in text
    assert not await ctx.chats.awarnings_of(message.chat.id,22)
    assert ctx.chats._member(message.chat.id,22)['warnings'][0]['reason']=='retain'


@pytest.mark.asyncio
async def test_warning_removal_audit_failure_reports_clear_committed(tmp_path):
    ctx,client,message=setup(tmp_path,'/rmwarn 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_DB'))
    await moderation.build(ctx)[1]['rmwarn'](client,message)
    text=str(message.replies[-1])
    assert 'Warnings cleared' in text and 'audit unconfirmed' in text
    assert 'PRIVATE_DB' not in text


@pytest.mark.asyncio
async def test_resetall_confirmation_card_and_final_rights_recheck(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/resetallwarns')
    handler=moderation.build(ctx)[1]['resetallwarns']
    await handler(client,message)
    assert 'confirm' in str(message.replies[-1])
    message.text='/resetallwarns confirm'
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await handler(client,message)
    assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_removal_parser_provider_error_redacted_and_no_warning_lost(tmp_path):
    ctx,client,message=setup(tmp_path,'/rmwarn @target')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    client.get_users=AsyncMock(side_effect=ValueError('PRIVATE_TOKEN'))
    await moderation.build(ctx)[1]['rmwarn'](client,message)
    assert 'PRIVATE_TOKEN' not in str(message.replies)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1


@pytest.mark.asyncio
async def test_unwarn_denied_personal_member_cannot_clear(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/unwarn 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    await moderation.build(ctx)[1]['unwarn'](client,message)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1


@pytest.mark.asyncio
async def test_group_resetwarns_final_auth_and_committed_audit_error(tmp_path):
    from agent.modules import group
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/resetwarns 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    call=group.build(ctx)[1]['resetwarns']
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER),fixtures.member(fixtures.MEMBER)])
    await call(client,message)
    assert len(await ctx.chats.awarnings_of(message.chat.id,22))==1
    ctx,client,message=setup(tmp_path/'audit','/resetwarns 22')
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='retain')
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_AUDIT'))
    await group.build(ctx)[1]['resetwarns'](client,message)
    assert not await ctx.chats.awarnings_of(message.chat.id,22)
    text=str(message.replies[-1])
    assert 'Committed' in text and 'audit unconfirmed' in text
    assert 'PRIVATE_AUDIT' not in text
