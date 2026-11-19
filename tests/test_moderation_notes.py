"""Notes use canonical member storage and preserve reply text without leaking it to logs."""
import os
import uuid
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation


@pytest.mark.asyncio
async def test_reply_note_keeps_first_word_and_rich_ack(tmp_path):
    ctx,client,message=setup(tmp_path,'/note first word <private>')
    message.reply_to_message=NS(chat=message.chat,from_user=NS(id=22))
    await moderation.build(ctx)[1]['note'](client,message)
    assert ctx.chats.note_of(message.chat.id,22)=='first word <private>'
    text=str(message.replies[-1])
    assert 'Note saved' in text and 'Moderator' in text
    assert '<private>' not in text


@pytest.mark.asyncio
async def test_username_note_and_no_global_owner_bypass(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/note @target keep all words')
    await moderation.build(ctx)[1]['note'](client,message)
    client.get_users.assert_awaited_once_with('@target')
    assert ctx.chats.note_of(message.chat.id,22)=='keep all words'
    client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    message.text='/note 22 overwrite'
    await moderation.build(ctx)[1]['note'](client,message)
    assert ctx.chats.note_of(message.chat.id,22)=='keep all words'


@pytest.mark.asyncio
async def test_pg_note_serialization_scope_restart_and_stale_document(tmp_path):
    from agent.platform.member_notes import operate
    from agent.platform.chats import ChatStore
    from agent.platform.db import Database
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='notes:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        store=ChatStore(tmp_path,db=db)
        async with db._pool.acquire() as conn:
            await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)',db.name_for('chats'),'{"-100":{"members":{"22":{"note":"legacy original"}}}}')
        assert (await operate(store,-100,22))=={'body':'legacy original','version':0}
        await asyncio.gather(*(operate(store,-100,22,body='note'+str(i),actor=11) for i in range(4)))
        result=await operate(ChatStore(tmp_path,db=db),-100,22)
        assert result['version']==4 and result['body'].startswith('note')
        async with db._pool.acquire() as conn:
            assert await conn.fetchval('SELECT count(*) FROM agent_member_note_changes WHERE tenant=$1 AND group_id=-100 AND user_id=22',db.scope)==4
        assert (await operate(store,-200,22))['body']==''
        assert (await operate(store,-100,33))['body']==''
        async with db._pool.acquire() as conn:
            await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb) ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value',db.name_for('chats'),'{"-100":{"members":{"22":{"note":"stale"}}}}')
        assert (await operate(store,-100,22))==result
        other=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            assert (await operate(ChatStore(tmp_path,db=other),-100,22))['body']==''
        finally:
            await other.close()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_note_audit_failure_preserves_committed_note(tmp_path):
    from unittest.mock import Mock
    ctx,client,message=setup(tmp_path,'/note 22 PRIVATE_BODY')
    ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_DB'))
    await moderation.build(ctx)[1]['note'](client,message)
    assert ctx.chats.note_of(message.chat.id,22)=='PRIVATE_BODY'
    text=str(message.replies[-1])
    assert 'Note saved' in text and 'audit unconfirmed' in text
    assert 'PRIVATE_BODY' not in text and 'PRIVATE_DB' not in text


@pytest.mark.asyncio
async def test_note_invalid_or_revoked_input_never_overwrites(tmp_path):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/note 22 '+'x'*2001)
    ctx.chats.set_note(message.chat.id,22,'original')
    await moderation.build(ctx)[1]['note'](client,message)
    assert ctx.chats.note_of(message.chat.id,22)=='original'
    message.text='/note 22 replacement'
    client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
    await moderation.build(ctx)[1]['note'](client,message)
    assert ctx.chats.note_of(message.chat.id,22)=='original'


@pytest.mark.asyncio
async def test_disconnected_note_store_never_falls_back_to_local(tmp_path):
    from agent.platform.member_notes import operate,NoteError
    ctx,_,message=setup(tmp_path,'')
    ctx.chats.set_note(message.chat.id,22,'stale local')
    ctx.chats._db=NS(connected=False,_pool=None)
    with pytest.raises(NoteError,match='unavailable'):
        await operate(ctx.chats,message.chat.id,22)
    with pytest.raises(NoteError,match='unavailable'):
        await operate(ctx.chats,message.chat.id,22,body='replacement',actor=11)
