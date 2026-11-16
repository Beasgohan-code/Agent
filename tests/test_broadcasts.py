"""Real PostgreSQL admission concurrency and tenant isolation, synthetic Telegram."""
import os
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType
from agent.platform.db import Database
from agent.platform.broadcasts import admit


@pytest.mark.asyncio
async def test_pg_broadcast_admission_once_and_scoped():
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    import asyncio
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='broadcast:'+uuid.uuid4().hex, required=True)
    assert await db.connect()
    ctx = NS(db=db, settings=NS(owner_id=11))
    try:
        results = await asyncio.gather(*(admit(ctx, 1, 11, 2, '-user', [22,33]) for _ in range(5)))
        assert results.count(True) == 1
        async with db._pool.acquire() as conn:
            assert await conn.fetchval('SELECT count(*) FROM agent_broadcast_items WHERE tenant=$1',db.scope) == 2
        db.scope += ':other'
        assert await admit(ctx, 1, 11, 2, '-user', [22])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unauthorized_broadcast_has_no_effect():
    from agent.modules.ops.broadcast import broadcast
    bot = NS(forward_messages=AsyncMock())
    item = NS(text='/broadcast -user', from_user=NS(id=22), chat=NS(id=22,type=ChatType.PRIVATE), reply=AsyncMock())
    await broadcast(NS(settings=NS(owner_id=11)),bot,item)
    bot.forward_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_pg_forward_records_ack_and_duplicate_does_not_replay():
    from agent.modules.ops.broadcast import broadcast
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='broadcast:'+uuid.uuid4().hex, required=True)
    assert await db.connect()
    ctx = NS(db=db, settings=NS(owner_id=11))
    db.save('users', {'22': 1, '33': 1})
    source = NS(id=2, chat=NS(id=11))
    item = NS(id=1,text='/broadcast -user',from_user=NS(id=11),chat=NS(id=11,type=ChatType.PRIVATE),reply_to_message=source,reply=AsyncMock())
    bot = NS(forward_messages=AsyncMock(side_effect=[NS(id=50), RuntimeError('SECRET')]))
    try:
        await broadcast(ctx, bot, item)
        assert bot.forward_messages.await_count == 2
        await broadcast(ctx, bot, item)
        assert bot.forward_messages.await_count == 2
        assert 'already admitted' in str(item.reply.await_args.args[0])
        async with db._pool.acquire() as conn:
            rows = await conn.fetch('SELECT recipient,outcome,destination_id FROM agent_broadcast_items WHERE tenant=$1 ORDER BY recipient',db.scope)
        assert [(r['outcome'], r['destination_id']) for r in rows] == [('forwarded',50),('unconfirmed',None)]
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['group','pin','protected','db_down'])
async def test_refusals_never_forward(mode):
    from agent.modules.ops.broadcast import broadcast
    bot = NS(forward_messages=AsyncMock())
    source = NS(id=2, chat=NS(id=11),has_protected_content=mode=='protected')
    item = NS(id=1,text='/broadcast '+('-pin' if mode=='pin' else '-user'),from_user=NS(id=11),chat=NS(id=-100 if mode=='group' else 11,type=ChatType.SUPERGROUP if mode=='group' else ChatType.PRIVATE),reply_to_message=source,reply=AsyncMock())
    await broadcast(NS(settings=NS(owner_id=11),db=None),bot,item)
    bot.forward_messages.assert_not_awaited()
