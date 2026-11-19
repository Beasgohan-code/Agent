"""Expiry is snapshotted on issue, never deletes history or expires restrictions."""
import os
import time
import uuid
import pytest
import test_group as fixtures
from agent.modules import group


@pytest.mark.asyncio
async def test_warntime_sets_policy_and_new_warnings_expire_without_losing_history(tmp_path,monkeypatch):
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    message=fixtures.FakeMessage('/warntime 2m')
    await group.build(ctx)[1]['warntime'](fixtures.FakeClient(),message)
    now=time.time()
    monkeypatch.setattr('agent.platform.chats.time.time',lambda:now)
    assert await ctx.chats.aadd_warning(fixtures.CHAT,22,moderator_id=11,reason='retained')==1
    warning=(await ctx.chats.awarnings_of(fixtures.CHAT,22))[0]
    assert warning['expires_at']==now+120
    monkeypatch.setattr('agent.platform.chats.time.time',lambda:now+121)
    assert await ctx.chats.awarnings_of(fixtures.CHAT,22)==[]
    history=ctx.chats._member(fixtures.CHAT,22)['warnings']
    assert history[0]['reason']=='retained' and history[0]['expired_at']==now+121
    assert not await ctx.chats.aclear_warning(fixtures.CHAT,22)


@pytest.mark.asyncio
async def test_pg_warning_expiry_survives_restart_and_policy_change(tmp_path):
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    from agent.platform.warning_policy import operate
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    db=Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='expiry:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        store=ChatStore(tmp_path,db=db)
        await operate(store,-100,actor=11,changes={'expiry_seconds':60})
        assert await store.aadd_warning(-100,22,moderator_id=11,reason='retain')==1
        await operate(store,-100,actor=11,changes={'expiry_seconds':0})
        assert len(await ChatStore(tmp_path,db=db).awarnings_of(-100,22))==1
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE agent_member_warnings SET payload=jsonb_set(payload,'{0,expires_at}',to_jsonb(1::int)) WHERE tenant=$1 AND group_id=-100 AND user_id=22",db.scope)
        assert await ChatStore(tmp_path,db=db).aactive_warning_count(-100,22)==0
        async with db._pool.acquire() as conn:
            import json
            raw=await conn.fetchval('SELECT payload FROM agent_member_warnings WHERE tenant=$1 AND group_id=-100 AND user_id=22',db.scope)
            history=json.loads(raw) if isinstance(raw,str) else raw
            assert history[0]['reason']=='retain' and not history[0]['active']
            assert history[0]['expired_at']>1
        assert await store.aadd_warning(-100,22,moderator_id=11,reason='permanent')==1
        assert (await store.awarnings_of(-100,22))[0].get('expires_at') is None
        # A group reset must not count already-expired but not-yet-read records.
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE agent_member_warnings SET payload=jsonb_set(payload,'{1,expires_at}',to_jsonb(1::int)) WHERE tenant=$1 AND group_id=-100 AND user_id=22",db.scope)
        from agent.platform.warnings import reset_group
        assert await reset_group(store,-100,actor=11,request_id=99)==0
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('args',['0s','59s','367d','999999999999999d','2m extra','forever'])
async def test_invalid_warntime_no_policy_change(tmp_path,args):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    await group.build(ctx)[1]['warntime'](fixtures.FakeClient(),fixtures.FakeMessage('/warntime '+args))
    assert (await operate(ctx.chats,fixtures.CHAT))['expiry_seconds']==0


@pytest.mark.asyncio
async def test_setting_changes_never_rewrite_existing_warnings(tmp_path):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    await ctx.chats.aadd_warning(fixtures.CHAT,22,moderator_id=11,reason='legacy')
    commands=group.build(ctx)[1]
    await commands['warntime'](fixtures.FakeClient(),fixtures.FakeMessage('/warntime 1m'))
    await ctx.chats.aadd_warning(fixtures.CHAT,22,moderator_id=11,reason='timed')
    await commands['warntime'](fixtures.FakeClient(),fixtures.FakeMessage('/warntime off'))
    assert (await operate(ctx.chats,fixtures.CHAT))['expiry_seconds']==0
    rows=await ctx.chats.awarnings_of(fixtures.CHAT,22)
    assert rows[0]['expires_at'] is None and rows[1]['expires_at'] is not None


@pytest.mark.asyncio
async def test_warntime_denied_before_policy_write(tmp_path):
    from agent.platform.warning_policy import operate
    ctx=fixtures.ctx.__wrapped__(tmp_path)
    await group.build(ctx)[1]['warntime'](fixtures.FakeClient(caller=fixtures.MEMBER),fixtures.FakeMessage('/warntime 1h'))
    assert (await operate(ctx.chats,fixtures.CHAT))['expiry_seconds']==0


@pytest.mark.asyncio
async def test_old_canonical_policy_without_expiry_remains_readable(tmp_path):
    from agent.platform.warning_policy import validate
    assert validate({'limit':4,'action':'ban'})=={'limit':4,'action':'ban','expiry_seconds':0}
