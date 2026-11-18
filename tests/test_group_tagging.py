"""Real PostgreSQL opt-in tagging foundation; no scraped member lists."""
import asyncio
import os
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.platform.db import Database


@pytest.mark.asyncio
async def test_tag_registry_always_available_scope_and_consent():
    from agent.platform.group_tagging import operate
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tags:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        assert await operate(db,-100)=={'count':0,'joined':False}
        await operate(db,-100)
        await asyncio.gather(*(operate(db,-100,join=True,user=22) for _ in range(8)))
        assert await operate(db,-100,user=22)=={'count':1,'joined':True}
        assert (await operate(db,-200,user=22))['count']==0
        other=Database(url,scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            assert (await operate(other,-100,user=22))['count']==0
        finally:
            await other.close()
        async with db._pool.acquire() as conn:
            await conn.execute('UPDATE agent_tag_settings SET enabled=false WHERE tenant=$1',db.scope)
        assert (await operate(db,-100,user=22))['count']==1
        await operate(db,-100,join=True,user=22)
        await operate(db,-100,join=False,user=22)
        assert (await operate(db,-100))['count']==0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_tag_controls_current_authority_and_membership(tmp_path):
    from test_mute_target_parity import setup
    from agent.modules import group
    from agent.platform.actions import ActionRouter
    from agent.platform.group_tagging import operate
    from pyrogram.enums import ChatMemberStatus as S
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tagui:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    ctx,client,message=setup(tmp_path,'/allsettings')
    ctx.db=db
    ctx.actions=ActionRouter()
    try:
        commands=group.build(ctx)[1]
        await commands['allsettings'](client,message)
        assert 'Always available' in str(message.replies[-1])
        query=NS(message=message,from_user=NS(id=22),data=f'tagopt:{message.chat.id}:join',answer=AsyncMock())
        client.get_chat_member=AsyncMock(return_value=NS(status=S.MEMBER))
        await ctx.actions.dispatch(client,query)
        assert (await operate(db,message.chat.id,user=22))['joined']
        client.get_chat_member=AsyncMock(return_value=NS(status=S.LEFT))
        query.from_user=NS(id=33)
        await ctx.actions.dispatch(client,query)
        assert (await operate(db,message.chat.id))['count']==1
        message.text='/allsettings off'
        from test_moderation import FakeClient
        await commands['allsettings'](FakeClient(),message)
        assert 'always available' in str(message.replies[-1])
        assert (await operate(db,message.chat.id))['count']==1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_tag_store_requires_pg_and_valid_personal_id():
    from agent.platform.group_tagging import operate,TagError
    for db in (None,NS(connected=False)):
        with pytest.raises(TagError):
            await operate(db,-100)
    with pytest.raises(TagError):
        await operate(None,-100,join=True,user=True)


@pytest.mark.asyncio
async def test_tag_registry_capacity_and_concurrent_withdrawal():
    from agent.platform.group_tagging import operate,TagError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tagcap:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        await operate(db,-100)
        async with db._pool.acquire() as conn:
            await conn.execute('INSERT INTO agent_tag_members(tenant,group_id,user_id) SELECT $1,-100,n FROM generate_series(1,500) AS n',db.scope)
        with pytest.raises(TagError,match='500'):
            await operate(db,-100,join=True,user=501)
        assert (await operate(db,-100))['count']==500
        assert (await operate(db,-100,join=True,user=1))['count']==500
        await asyncio.gather(*(operate(db,-100,join=False,user=1) for _ in range(4)))
        assert (await operate(db,-100))['count']==499
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_tag_run_claim_concurrency_rate_and_withdrawal():
    from agent.platform.group_tagging import operate,start_run,claim_batch,settle_batch,stop_run,TagError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tagrun:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        await operate(db,-100)
        for uid in range(21,29):
            await operate(db,-100,join=True,user=uid)
        run=await start_run(db,-100,actor=11,style="emoji")
        await operate(db,-100,join=False,user=21)
        results=await asyncio.gather(*(claim_batch(db,-100,run,actor=11) for _ in range(4)),return_exceptions=True)
        batches=[result for result in results if isinstance(result,dict)]
        assert len(batches)==1 and batches[0]['members']==[22,23,24,25]
        assert batches[0]['style']=='emoji'
        with pytest.raises(TagError):
            await claim_batch(db,-200,run,actor=11)
        await settle_batch(db,-100,run,confirmed=True)
        with pytest.raises(TagError,match='30'):
            await claim_batch(db,-100,run,actor=11)
        await stop_run(db,-100,actor=11)
        with pytest.raises(TagError):
            await claim_batch(db,-100,run,actor=11)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_tag_batch_failure_no_replay_or_silent_restart():
    from agent.platform.group_tagging import operate,start_run,claim_batch,settle_batch,stop_run,TagError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='taguncertain:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        await operate(db,-100)
        await operate(db,-100,join=True,user=22)
        run=await start_run(db,-100,actor=11)
        await claim_batch(db,-100,run,actor=11)
        await settle_batch(db,-100,run,confirmed=False)
        with pytest.raises(TagError):
            await claim_batch(db,-100,run,actor=11)
        with pytest.raises(TagError):
            await start_run(db,-100,actor=11)
        await stop_run(db,-100,actor=11)
        async with db._pool.acquire() as conn:
            row=await conn.fetchrow('SELECT state,members FROM agent_tag_runs WHERE tenant=$1 AND id=$2',db.scope,run)
        assert row['state']=='stopped' and not row['members']
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['normal','timeout','rights_lost','emoji'])
async def test_tag_command_sends_only_opted_in_batch_and_real_stop(tmp_path,outcome):
    from test_mute_target_parity import setup
    from agent.platform.group_tagging import operate
    from agent.modules import group
    from agent.platform.actions import ActionRouter
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tagsend:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    ctx,client,message=setup(tmp_path,'@eall' if outcome=='emoji' else '/tagall')
    ctx.db=db
    ctx.actions=ActionRouter()
    client.send_message=AsyncMock(return_value=NS(id=500))
    try:
        await operate(db,message.chat.id)
        for uid in range(21,29):
            await operate(db,message.chat.id,join=True,user=uid)
        if outcome=='timeout':
            client.send_message.side_effect=TimeoutError('PRIVATE_TOKEN')
        if outcome=='rights_lost':
            from pyrogram.enums import ChatMemberStatus as S
            checks=0
            async def member(chat,uid):
                nonlocal checks
                if uid==11:
                    checks+=1
                    return NS(status=S.MEMBER if checks>=3 else S.ADMINISTRATOR,privileges=NS(can_manage_chat=True))
                return NS(status=S.MEMBER)
            client.get_chat_member=AsyncMock(side_effect=member)
        commands=group.build(ctx)[1]
        await commands['eall' if outcome=='emoji' else 'tagall'](client,message)
        if outcome not in ('normal','emoji'):
            assert client.send_message.await_count==(1 if outcome=='timeout' else 0)
            async with db._pool.acquire() as conn:
                assert await conn.fetchval('SELECT state FROM agent_tag_runs WHERE tenant=$1',db.scope)=='review'
            assert 'PRIVATE_TOKEN' not in str(message.replies)
            return
        client.send_message.assert_awaited_once()
        body=client.send_message.call_args.kwargs['text']
        assert body.count('tg://user?id=')==5 and 'id=26' not in body
        if outcome=='emoji':
            assert '>Member ' not in body
            async with db._pool.acquire() as conn:
                assert await conn.fetchval('SELECT style FROM agent_tag_runs WHERE tenant=$1',db.scope)=='emoji'
        assert 'paused' in str(message.replies[-1])
        async with db._pool.acquire() as conn:
            request=await conn.fetchval('SELECT id FROM agent_tag_runs WHERE tenant=$1',db.scope)
        query=NS(message=message,from_user=message.from_user,data=f'tagrun:{request}:stop',answer=AsyncMock())
        await ctx.actions.dispatch(client,query)
        query.data=f'tagrun:{request}:resume'
        await ctx.actions.dispatch(client,query)
        assert client.send_message.await_count==1
    finally:
        await db.close()
