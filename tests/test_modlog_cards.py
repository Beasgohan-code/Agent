"""Bounded, authorized recent audit reader; never complete/live state proof."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_moderation as fixtures
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
async def test_recent_log_pages_are_bounded_and_include_actor_source(tmp_path):
    ctx,client,message=setup(tmp_path,'/modlog 2')
    for i in range(12):
        ctx.chats.log(message.chat.id,'warn',actor_id=11,target_id=22,reason=f'row{i} '+'x'*2000)
    await moderation.build(ctx)[1]['modlog'](client,message)
    text=str(message.replies[-1])
    assert 'Page 2/4' in text and 'Moderator' in text and '11' in text
    assert 'Local audit' in text and 'not a complete' in text
    assert len(text)<3500 and 'x'*161 not in text


@pytest.mark.asyncio
async def test_rechecks_authority_after_reads_before_disclosure(tmp_path,monkeypatch):
    import agent.modules.moderation.modlog_card as module
    ctx,client,message=setup(tmp_path,'/modlog')
    monkeypatch.setattr(module,'policy_history',AsyncMock(return_value=[{'action':'PRIVATE_ACTION','at':1}]))
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['modlog'](client,message)
    assert 'changed' in str(message.replies[-1]) and 'PRIVATE_ACTION' not in str(message.replies)


@pytest.mark.asyncio
@pytest.mark.parametrize('identity',['member','bot','anonymous'])
async def test_rejects_nonpersonal_or_nonadmin_without_read(tmp_path,monkeypatch,identity):
    import agent.modules.moderation.modlog_card as module
    ctx,client,message=setup(tmp_path,'/modlog')
    read=AsyncMock(return_value=[])
    monkeypatch.setattr(module,'policy_history',read)
    if identity=='member':
        client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    elif identity=='bot':
        message.from_user=NS(id=11,is_bot=True)
    else:
        message.sender_chat=message.chat
    await moderation.build(ctx)[1]['modlog'](client,message)
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_source_never_shows_partial_or_provider_errors(tmp_path,monkeypatch):
    import agent.modules.moderation.modlog_card as module
    ctx,client,message=setup(tmp_path,'/modlog')
    ctx.chats.log(message.chat.id,'PRIVATE_LOCAL',actor_id=11)
    read=AsyncMock(side_effect=RuntimeError('PRIVATE_DSN'))
    monkeypatch.setattr(module,'rules_history',read)
    await moderation.build(ctx)[1]['modlog'](client,message)
    text=str(message.replies[-1])
    assert 'unavailable' in text and 'PRIVATE_' not in text
    read.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_and_invalid_pages_are_explicit(tmp_path):
    ctx,client,message=setup(tmp_path,'/modlog')
    call=moderation.build(ctx)[1]['modlog']
    await call(client,message)
    assert 'No recent entries' in str(message.replies[-1])
    for args in ['0','-1','2','９','1 extra']:
        message.text='/modlog '+args
        await call(client,message)
        assert 'page' in str(message.replies[-1]).lower() and 'No recent entries' not in str(message.replies[-1])


@pytest.mark.asyncio
async def test_merged_sources_keep_outcome_and_latest_order(tmp_path,monkeypatch):
    import agent.modules.moderation.modlog_card as module
    ctx,client,message=setup(tmp_path,'/modlog')
    monkeypatch.setattr(module,'restriction_history',AsyncMock(return_value=[{'action':'kick:pending','actor':11,'target':22,'at':200,'reason':'unknown result'}]))
    monkeypatch.setattr(module,'trust_history',AsyncMock(return_value=[{'action':'approve','actor':11,'target':22,'at':300}]))
    await moderation.build(ctx)[1]['modlog'](client,message)
    text=str(message.replies[-1])
    assert text.index('APPROVE')<text.index('KICK:PENDING')
    assert 'Canonical audit' in text and 'unknown result' in text


@pytest.mark.asyncio
async def test_real_pg_log_reads_committed_scoped_history(tmp_path):
    import os
    import uuid
    from agent.platform.db import Database
    from agent.platform.antispam import change_policy
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    ctx,client,message=setup(tmp_path,'/modlog')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='modlog:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    ctx.db=db
    try:
        await change_policy(ctx,message.chat.id,'links','off',actor=11)
        await change_policy(ctx,-200,'keyword','PRIVATE_OTHER_GROUP',actor=11)
        await moderation.build(ctx)[1]['modlog'](client,message)
        text=str(message.replies[-1])
        assert 'ANTISPAM' in text and 'Canonical audit' in text and 'links' in text
        assert 'keyword' not in text and 'PRIVATE_OTHER_GROUP' not in text
        other=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            ctx.db=other
            await moderation.build(ctx)[1]['modlog'](client,message)
            assert 'No recent entries' in str(message.replies[-1])
        finally:
            await other.close()
    finally:
        await db.close()
