"""Real PostgreSQL opt-in tagging foundation; no scraped member lists."""
import asyncio
import os
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.platform.db import Database


@pytest.mark.asyncio
async def test_tag_registry_concurrency_scope_disable_and_consent():
    from agent.platform.group_tagging import operate,TagError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tags:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        assert await operate(db,-100)=={'enabled':False,'count':0,'joined':False}
        with pytest.raises(TagError):
            await operate(db,-100,join=True,user=22)
        await operate(db,-100,enabled=True,actor=11)
        await asyncio.gather(*(operate(db,-100,join=True,user=22) for _ in range(8)))
        assert await operate(db,-100,user=22)=={'enabled':True,'count':1,'joined':True}
        assert (await operate(db,-200,user=22))['count']==0
        other=Database(url,scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            assert (await operate(other,-100,user=22))['count']==0
        finally:
            await other.close()
        await operate(db,-100,enabled=False,actor=11)
        await operate(db,-100,enabled=True,actor=11)
        assert (await operate(db,-100,user=22))['count']==0
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
    ctx,client,message=setup(tmp_path,'/allsettings on')
    ctx.db=db
    ctx.actions=ActionRouter()
    try:
        commands=group.build(ctx)[1]
        await commands['allsettings'](client,message)
        assert (await operate(db,message.chat.id))['enabled']
        query=NS(message=message,from_user=NS(id=22),data=f'tagopt:{message.chat.id}:join',answer=AsyncMock())
        client.get_chat_member=AsyncMock(return_value=NS(status=S.MEMBER))
        await ctx.actions.dispatch(client,query)
        assert (await operate(db,message.chat.id,user=22))['joined']
        client.get_chat_member=AsyncMock(return_value=NS(status=S.LEFT))
        query.from_user=NS(id=33)
        await ctx.actions.dispatch(client,query)
        assert (await operate(db,message.chat.id))['count']==1
        message.text='/allsettings off'
        await commands['allsettings'](client,message)
        assert (await operate(db,message.chat.id))['enabled']
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
async def test_tag_registry_capacity_and_disable_race():
    from agent.platform.group_tagging import operate,TagError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tagcap:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        await operate(db,-100,enabled=True,actor=11)
        async with db._pool.acquire() as conn:
            await conn.execute('INSERT INTO agent_tag_members(tenant,group_id,user_id) SELECT $1,-100,n FROM generate_series(1,500) AS n',db.scope)
        with pytest.raises(TagError,match='500'):
            await operate(db,-100,join=True,user=501)
        assert (await operate(db,-100))['count']==500
        assert (await operate(db,-100,join=True,user=1))['count']==500
        await asyncio.gather(operate(db,-100,enabled=False,actor=11),operate(db,-100,join=True,user=1),return_exceptions=True)
        assert await operate(db,-100)=={'enabled':False,'count':0,'joined':False}
    finally:
        await db.close()
