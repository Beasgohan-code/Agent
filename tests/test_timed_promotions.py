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


@pytest.mark.asyncio
@pytest.mark.parametrize('case,expected,calls',[
    ('normal','closed',1),('changed_rights','review',0),('wrong_promoter','review',0),
    ('wrong_bot','review',0),('prepared','review',0),('already_member','closed',0),
    ('ambiguous_ack','review',1),('uneditable','review',0),
    ('bot_revoked','review',0),('telegram_error','review',1),('new_right','review',0)])
async def test_due_promotion_recovery_real_pg_with_simulated_telegram(case,expected,calls):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatMemberStatus as Status
    from pyrogram.types import ChatPrivileges
    from agent.platform.timed_promotions import reserve,finish,read,reconcile_due
    url=os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostgreSQL required')
    db=Database(url,scope='expiry:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    try:
        identity=await reserve(db,-100,22,actor=11,bot=99,expires=datetime.now(timezone.utc)+timedelta(minutes=5),rights={'can_manage_chat':True})
        if case!='prepared':
            await finish(db,identity,'active',expected='prepared')
        async with db._pool.acquire() as conn:
            await conn.execute("UPDATE agent_timed_promotions SET expires_at=now()-interval '1 minute' WHERE tenant=$1",db.scope)
        target=NS(status=Status.ADMINISTRATOR,privileges=ChatPrivileges(can_manage_chat=True),promoted_by=NS(id=99),can_be_edited=True)
        if case=='new_right':
            target.privileges.can_manage_tags=True
        if case=='changed_rights':
            target.privileges.can_delete_messages=True
        if case=='wrong_promoter':
            target.promoted_by.id=88
        if case=='uneditable':
            target.can_be_edited=False
        if case=='already_member':
            target.status=Status.MEMBER
        client=NS(get_me=AsyncMock(return_value=NS(id=88 if case=='wrong_bot' else 99)),
            get_chat_member=AsyncMock(side_effect=lambda chat,uid: NS(status=Status.ADMINISTRATOR,privileges=ChatPrivileges(can_promote_members=case!='bot_revoked')) if uid==99 else target),
            promote_chat_member=AsyncMock(return_value=False if case=='ambiguous_ack' else True))
        if case=='telegram_error':
            client.promote_chat_member.side_effect=TimeoutError('PRIVATE_TOKEN')
        await asyncio.gather(reconcile_due(db,client),reconcile_due(db,client))
        row=await read(db,identity)
        assert row['state']==expected
        assert client.promote_chat_member.await_count==calls
        if calls:
            import inspect
            privileges=client.promote_chat_member.await_args.kwargs['privileges']
            assert all(getattr(privileges,key) is False for key in inspect.signature(ChatPrivileges).parameters)
        await reconcile_due(db,client)
        assert client.promote_chat_member.await_count==calls
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reconciler_db_outage_never_contacts_telegram():
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.platform.timed_promotions import reconcile_due,PromotionError
    client=NS(get_me=AsyncMock())
    with pytest.raises(PromotionError):
        await reconcile_due(NS(connected=False),client)
    client.get_me.assert_not_awaited()
