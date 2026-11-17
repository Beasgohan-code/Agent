"""Canonical warning policy is atomic across writers and tenant/group scoped."""
import os
import uuid
import asyncio
import pytest
import test_group as fixtures
from agent.modules import group


@pytest.mark.asyncio
async def test_warning_policy_pg_atomic_fields_isolation_and_restart(tmp_path):
    from agent.platform.warning_policy import operate,PolicyError
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='warnpolicy:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    store=ChatStore(tmp_path,db=db)
    try:
        first=await operate(store,-100)
        assert first=={'limit':3,'action':'mute','expiry_seconds':0}
        await asyncio.gather(operate(store,-100,actor=11,changes={'action':'ban','expiry_seconds':0}),operate(store,-100,actor=22,changes={'limit':5}))
        assert await operate(store,-100)=={'limit':5,'action':'ban','expiry_seconds':0}
        assert (await operate(store,-200))['action']=='mute'
        reloaded=ChatStore(tmp_path,db=db)
        assert (await operate(reloaded,-100))['limit']==5
        with pytest.raises(PolicyError):
            await operate(store,-100,actor=11,changes={'limit':4,'action':'explode'})
        assert (await operate(store,-100))['limit']==5
        other=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope=db.scope+':other',required=True)
        assert await other.connect()
        try:
            assert await operate(ChatStore(tmp_path,db=other),-100)=={'limit':3,'action':'mute','expiry_seconds':0}
        finally:
            await other.close()
        async with db._pool.acquire() as conn:
            count=await conn.fetchval('SELECT count(*) FROM agent_warning_policy_history WHERE tenant=$1 AND group_id=-100',db.scope)
            assert count==3
            await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb) ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value',db.name_for('chats'),'{"-100":{"settings":{"warn_limit":1,"warn_action":"kick"}}}')
        assert await operate(reloaded,-100)=={'limit':5,'action':'ban','expiry_seconds':0}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_warnmode_and_legacy_limit_share_policy(tmp_path):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    handlers=group.build(ctx)[1]
    client=fixtures.FakeClient()
    for command in ['/warnmode ban','/warnlimit 4']:
        await handlers[command.split()[0][1:]](client,fixtures.FakeMessage(command))
    assert await operate(ctx.chats,fixtures.CHAT)=={'limit':4,'action':'ban','expiry_seconds':0}


@pytest.mark.asyncio
async def test_bad_warnlimit_never_partially_changes_threshold(tmp_path):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    await group.build(ctx)[1]['warnlimit'](fixtures.FakeClient(),fixtures.FakeMessage('/warnlimit 7 explode'))
    assert (await operate(ctx.chats,fixtures.CHAT))['limit']==3


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['/warnmode explode','/warnlimit 4 ban extra','/warnlimit 0 nope','/warnlimit 99999999999999999999999999'])
async def test_invalid_policy_command_is_atomic(tmp_path,command):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    message=fixtures.FakeMessage(command)
    await group.build(ctx)[1][command.split()[0][1:]](fixtures.FakeClient(),message)
    assert await operate(ctx.chats,fixtures.CHAT)=={'limit':3,'action':'mute','expiry_seconds':0}


@pytest.mark.asyncio
async def test_warnmode_denies_nonadmin_and_db_down_does_not_change_cache(tmp_path):
    from types import SimpleNamespace as NS
    from agent.platform.warning_policy import operate,PolicyError
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    message=fixtures.FakeMessage('/warnmode ban')
    await group.build(ctx)[1]['warnmode'](fixtures.FakeClient(caller=fixtures.MEMBER),message)
    assert await operate(ctx.chats,fixtures.CHAT)=={'limit':3,'action':'mute','expiry_seconds':0}
    ctx.chats._db=NS(connected=False,_pool=None)
    with pytest.raises(PolicyError,match='unavailable'):
        await operate(ctx.chats,fixtures.CHAT,actor=11,changes={'action':'ban','expiry_seconds':0})
