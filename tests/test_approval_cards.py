"""Approval command targeting, authority and honest rich cards."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_moderation as fixtures
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
async def test_approve_username_and_unapprove_id_rich_status(tmp_path):
    ctx,client,message=setup(tmp_path,'/approve @target')
    commands=moderation.build(ctx)[1]
    await commands['approve'](client,message)
    assert ctx.chats.is_trusted(message.chat.id,22)
    assert 'Approved member' in str(message.replies[-1]) and 'Moderator' in str(message.replies[-1])
    client.get_users.assert_awaited_once_with('@target')
    message.text='/unapprove 22'
    await commands['unapprove'](client,message)
    assert not ctx.chats.is_trusted(message.chat.id,22)
    assert 'Approval removed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_final_rights_loss_never_writes(tmp_path):
    ctx,client,message=setup(tmp_path,'/approve 22')
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['approve'](client,message)
    assert not ctx.chats.is_trusted(message.chat.id,22)
    assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_reply_and_text_mention_no_extra_arguments(tmp_path):
    ctx,client,message=setup(tmp_path,'/approve')
    message.reply_to_message=NS(chat=message.chat,from_user=NS(id=22))
    commands=moderation.build(ctx)[1]
    await commands['approve'](client,message)
    assert ctx.chats.is_trusted(message.chat.id,22)
    message.reply_to_message=None
    message.text='/unapprove Named Member'
    message.entities=[NS(offset=11,length=12,user=NS(id=22))]
    await commands['unapprove'](client,message)
    assert not ctx.chats.is_trusted(message.chat.id,22)
    message.entities=[]
    message.text='/approve 22 ignored'
    await commands['approve'](client,message)
    assert not ctx.chats.is_trusted(message.chat.id,22)


@pytest.mark.asyncio
async def test_approval_and_list_reauthorize_after_read(tmp_path,monkeypatch):
    import agent.modules.moderation.approvals as module
    ctx,client,message=setup(tmp_path,'/approval 22')
    read=AsyncMock(return_value={22})
    monkeypatch.setattr(module,'trusted_members',read)
    for command,text in [('approval','/approval 22'),('approved','/approved')]:
        message.text=text
        client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
        await moderation.build(ctx)[1][command](client,message)
        assert 'Approved member' not in str(message.replies[-1])
        assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_live_page_commands_and_invalid_pages(tmp_path):
    ctx,client,message=setup(tmp_path,'/approved 2')
    for uid in range(1,24):
        ctx.chats.toggle_trust(message.chat.id,uid)
    call=moderation.build(ctx)[1]['approved']
    await call(client,message)
    text=str(message.replies[-1])
    assert 'Page 2/2' in text and '23' in text and 'automatic' in text
    for page in ['0','-1','3','2 extra','９']:
        message.text='/approved '+page
        await call(client,message)
        assert 'Page 2/2' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_provider_failure_redacted_and_no_retry(tmp_path):
    ctx,client,message=setup(tmp_path,'/approve @target')
    client.get_users=AsyncMock(side_effect=RuntimeError('PRIVATE_TOKEN'))
    await moderation.build(ctx)[1]['approve'](client,message)
    assert 'PRIVATE_TOKEN' not in str(message.replies)
    assert 'unconfirmed' in str(message.replies[-1])
    client.get_users.assert_awaited_once()
    assert not ctx.chats.is_trusted(message.chat.id,22)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['bot','anonymous','external'])
async def test_no_bot_anonymous_or_external_reply_mutation(tmp_path,kind):
    ctx,client,message=setup(tmp_path,'/approve')
    message.reply_to_message=NS(chat=message.chat,from_user=NS(id=22))
    if kind=='bot':
        message.from_user=NS(id=11,is_bot=True)
    elif kind=='anonymous':
        message.sender_chat=message.chat
    else:
        message.reply_to_message.chat=NS(id=-200)
    await moderation.build(ctx)[1]['approve'](client,message)
    assert not ctx.chats.is_trusted(message.chat.id,22)


@pytest.mark.asyncio
async def test_duplicate_approve_does_not_toggle_and_status_matches(tmp_path):
    ctx,client,message=setup(tmp_path,'/approve 22')
    commands=moderation.build(ctx)[1]
    await commands['approve'](client,message)
    await commands['approve'](client,message)
    assert ctx.chats.is_trusted(message.chat.id,22)
    assert len(ctx.chats.history(message.chat.id))==1
    message.text='/approval 22'
    await commands['approval'](client,message)
    text=str(message.replies[-1])
    assert 'Approval status' in text and 'Current state' in text and 'Approved' in text


@pytest.mark.asyncio
async def test_local_audit_failure_is_unconfirmed_not_fake_denial(tmp_path):
    from unittest.mock import Mock
    ctx,client,message=setup(tmp_path,'/approve 22')
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_AUDIT'))
    await moderation.build(ctx)[1]['approve'](client,message)
    assert ctx.chats.is_trusted(message.chat.id,22)
    text=str(message.replies[-1])
    assert 'unconfirmed' in text and 'PRIVATE_AUDIT' not in text
    assert 'Approved member' not in text
