"""Anti-spam UI must reflect policy state without claiming live enforcement."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_moderation as fixtures
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
async def test_saved_policy_card_shows_actor_status_and_no_live_claim(tmp_path):
    ctx,client,message=setup(tmp_path,'/antispam links off')
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)['links_enabled'] is False
    text=str(message.replies[-1])
    assert 'Committed' in text and 'Moderator' in text
    assert 'not a live enforcement check' in text


@pytest.mark.asyncio
async def test_final_rights_loss_prevents_policy_write(tmp_path):
    ctx,client,message=setup(tmp_path,'/antispam off')
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)['flood_enabled']
    assert 'changed' in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('args',['off junk','on junk','keyword-clear junk','limit 1','limit 1001','limit ９','mute 29','mute 31622401'])
async def test_invalid_extra_or_out_of_range_input_never_mutates(tmp_path,args):
    ctx,client,message=setup(tmp_path,'/antispam '+args)
    before=dict(ctx.chats.antispam(message.chat.id))
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)==before
    assert not ctx.chats.history(message.chat.id)


@pytest.mark.asyncio
async def test_keyword_card_is_bounded_and_never_echoes_phrases(tmp_path):
    ctx,client,message=setup(tmp_path,'/antispam keyword <PRIVATE_PHRASE>')
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)['blocked_keywords']==['<private_phrase>']
    text=str(message.replies[-1])
    assert '<private_phrase>' not in text.lower()
    assert '1 configured' in text


@pytest.mark.asyncio
async def test_read_rechecks_authority_before_showing_policy(tmp_path,monkeypatch):
    import agent.modules.moderation.antispam_card as module
    ctx,client,message=setup(tmp_path,'/antispam')
    read=AsyncMock(return_value=ctx.chats.antispam(message.chat.id))
    monkeypatch.setattr(module,'read_policy',read)
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert 'changed' in str(message.replies[-1])
    assert 'Flood' not in str(message.replies[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['bot','anonymous'])
async def test_rejects_impersonal_callers(tmp_path,kind):
    ctx,client,message=setup(tmp_path,'/antispam off')
    if kind=='bot':
        message.from_user=NS(id=11,is_bot=True)
    else:
        message.sender_chat=message.chat
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)['flood_enabled']


@pytest.mark.asyncio
async def test_policy_failure_redacted_and_never_retried(tmp_path,monkeypatch):
    import agent.modules.moderation.antispam_card as module
    ctx,client,message=setup(tmp_path,'/antispam off')
    change=AsyncMock(side_effect=RuntimeError('PRIVATE_DSN'))
    monkeypatch.setattr(module,'change_policy',change)
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert 'PRIVATE_DSN' not in str(message.replies)
    assert 'unconfirmed' in str(message.replies[-1])
    change.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('args,key,expected',[('limit 2','flood_messages',2),('limit 1000','flood_messages',1000),('mute 30','mute_seconds',30),('mute 31622400','mute_seconds',31622400)])
async def test_inclusive_numeric_boundaries(tmp_path,args,key,expected):
    ctx,client,message=setup(tmp_path,'/antispam '+args)
    await moderation.build(ctx)[1]['antispam'](client,message)
    assert ctx.chats.antispam(message.chat.id)[key]==expected
    assert 'Committed' in str(message.replies[-1])


@pytest.mark.asyncio
async def test_current_settings_and_off_show_additional_flood_modes(tmp_path):
    from agent.platform.antispam import change_policy
    ctx,client,message=setup(tmp_path,'/antispam')
    await change_policy(ctx,message.chat.id,'consecutive',3,actor=11)
    command=moderation.build(ctx)[1]['antispam']
    await command(client,message)
    assert 'Current saved policy' in str(message.replies[-1])
    assert 'consecutive 3' in str(message.replies[-1])
    message.text='/antispam off'
    await command(client,message)
    assert ctx.chats.antispam(message.chat.id)['consecutive_limit']==0
    assert 'consecutive 0' in str(message.replies[-1])
