"""Durable admission for temporary promotions; no Telegram calls in store tests."""
import asyncio
import os
import uuid
from datetime import datetime,timedelta,timezone
import pytest
from agent.platform.db import Database


@pytest.mark.asyncio
async def test_timed_promotion_admission_restart_scope_and_active_uniqueness():
    from agent.platform.timed_promotions import reserve,finish,read,PromotionError
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='tpromote:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        end=datetime.now(timezone.utc)+timedelta(minutes=5)
        async def attempt():
            try:
                return await reserve(db,-100,22,actor=11,bot=99,expires=end,rights={'can_manage_chat':True})
            except PromotionError:
                return None
        results=await asyncio.gather(*(attempt() for _ in range(6)))
        ids=[r for r in results if r]
        assert len(ids)==1
        identity=ids[0]
        other=Database(url,scope=db.scope,required=True)
        assert await other.connect()
        try:
            row=await read(other,identity)
            assert row['state']=='prepared' and row['target_id']==22
            assert await read(other,identity,group=-200) is None
            await finish(other,identity,'active',expected='prepared')
            with pytest.raises(PromotionError):
                await finish(db,identity,'cancelled',expected='prepared')
            assert (await read(db,identity))['state']=='active'
            await finish(db,identity,'review',expected='active')
            with pytest.raises(PromotionError):
                await attempt_raise(db,end)
            await finish(db,identity,'closed',expected='review')
            assert await attempt_raise(db,end)
        finally:
            await other.close()
        isolated=Database(url,scope=db.scope+':other',required=True)
        assert await isolated.connect()
        try:
            assert await read(isolated,identity) is None
        finally:
            await isolated.close()
    finally:
        await db.close()


async def attempt_raise(db,end):
    from agent.platform.timed_promotions import reserve
    return await reserve(db,-100,22,actor=11,bot=99,expires=end,rights={'can_manage_chat':True})


@pytest.mark.asyncio
async def test_timed_promotion_refuses_offline_and_invalid_records():
    from types import SimpleNamespace as NS
    from agent.platform.timed_promotions import reserve,PromotionError
    end=datetime.now(timezone.utc)+timedelta(minutes=5)
    for fields in [dict(group=1,target=22),dict(group=-100,target=True)]:
        with pytest.raises(PromotionError):
            await reserve(None,**fields,actor=11,bot=99,expires=end,rights={'can_manage_chat':True})
    with pytest.raises(PromotionError):
        await reserve(NS(connected=False),-100,22,actor=11,bot=99,expires=end,rights={'can_manage_chat':True})
    for rights in [{},{'can_promote_members':True},{'can_manage_chat':'yes'}]:
        with pytest.raises(PromotionError):
            await reserve(None,-100,22,actor=11,bot=99,expires=end,rights=rights)
