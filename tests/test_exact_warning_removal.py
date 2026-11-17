"""Old warning-card controls never remove a newer warning, even under concurrency."""
import os
import uuid
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_mute_target_parity import setup
from agent.modules import moderation
from agent.platform.actions import ActionRouter


@pytest.mark.asyncio
async def test_exact_local_clear_does_not_remove_newer_warning(tmp_path):
    ctx,_,message=setup(tmp_path,'')
    first,second=uuid.uuid4().hex,uuid.uuid4().hex
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='old',warning_id=first)
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='new',warning_id=second)
    assert await ctx.chats.aclear_warning_id(message.chat.id,22,first,actor_id=11)
    assert not await ctx.chats.aclear_warning_id(message.chat.id,22,first,actor_id=11)
    assert [row['id'] for row in await ctx.chats.awarnings_of(message.chat.id,22)]==[second]
    assert ctx.chats._member(message.chat.id,22)['warnings'][0]['cleared_by']==11


@pytest.mark.asyncio
async def test_pg_exact_clear_concurrency_and_scope(tmp_path):
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='exactwarn:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        store=ChatStore(tmp_path,db=db)
        first,second=uuid.uuid4().hex,uuid.uuid4().hex
        await store.aadd_warning(-100,22,moderator_id=11,reason='old',warning_id=first)
        await store.aadd_warning(-100,22,moderator_id=11,reason='new',warning_id=second)
        assert not await store.aclear_warning_id(-200,22,first,actor_id=11)
        results=await asyncio.gather(*(store.aclear_warning_id(-100,22,first,actor_id=11) for _ in range(4)))
        assert sum(results)==1
        rows=await ChatStore(tmp_path,db=db).awarnings_of(-100,22)
        assert [row['id'] for row in rows]==[second]
        other=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            otherstore=ChatStore(tmp_path,db=other)
            await otherstore.aadd_warning(-100,22,moderator_id=11,reason='other tenant',warning_id=first)
            assert not await store.aclear_warning_id(-100,22,first,actor_id=11)
            assert await otherstore.aactive_warning_count(-100,22)==1
        finally:
            await other.close()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_warning_card_exact_control_routes_and_rejects_replay(tmp_path):
    ctx,client,message=setup(tmp_path,'/warn 22 old')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['warn'](client,message)
    buttons=[button for row in message.reply.await_args.kwargs['reply_markup'].inline_keyboard for button in row]
    button=next(button for button in buttons if 'Remove' in button.text)
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='new')
    query=NS(data=button.callback_data,from_user=NS(id=11),message=NS(id=500,chat=message.chat,reply=AsyncMock(return_value=NS(id=501))),answer=AsyncMock())
    await ctx.actions.dispatch(client,query)
    assert [row['reason'] for row in await ctx.chats.awarnings_of(message.chat.id,22)]==['new']
    await ctx.actions.dispatch(client,query)
    assert [row['reason'] for row in await ctx.chats.awarnings_of(message.chat.id,22)]==['new']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['other_chat','other_message','expired','nonadmin'])
async def test_exact_control_denies_forged_expired_or_unauthorized_press(tmp_path,mode):
    import test_moderation as fixtures
    ctx,client,message=setup(tmp_path,'/warn 22 old')
    ctx.actions=ActionRouter()
    message.reply=AsyncMock(return_value=NS(id=500))
    await moderation.build(ctx)[1]['warn'](client,message)
    buttons=[button for row in message.reply.await_args.kwargs['reply_markup'].inline_keyboard for button in row]
    data=next(button.callback_data for button in buttons if 'Remove' in button.text)
    query=NS(data=data,from_user=NS(id=11),message=NS(id=500,chat=message.chat,reply=AsyncMock()),answer=AsyncMock())
    if mode=='other_chat':
        query.message.chat=NS(id=-200,type=message.chat.type)
    elif mode=='other_message':
        query.message.id=501
    elif mode=='expired':
        for entry in ctx._warning_undo_entries.values():
            entry['expires']=0
    else:
        client.get_chat_member=AsyncMock(return_value=fixtures.member(fixtures.MEMBER))
    await ctx.actions.dispatch(client,query)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1
    query.message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_clear_expired_or_legacy_history_never_falls_back_to_latest(tmp_path):
    ctx,_,message=setup(tmp_path,'')
    warning=uuid.uuid4().hex
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='expired',warning_id=warning)
    ctx.chats._member(message.chat.id,22)['warnings'][0]['expires_at']=1
    await ctx.chats.aadd_warning(message.chat.id,22,moderator_id=11,reason='new')
    assert not await ctx.chats.aclear_warning_id(message.chat.id,22,warning,actor_id=11)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1
    ctx.chats._member(message.chat.id,22)['warnings'][-1].pop('id')
    assert not await ctx.chats.aclear_warning_id(message.chat.id,22,uuid.uuid4().hex,actor_id=11)
    assert await ctx.chats.aactive_warning_count(message.chat.id,22)==1
