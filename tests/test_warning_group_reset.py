"""Group-wide warning resets are atomic, scoped and do not erase history."""
import os
import uuid
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.platform.db import Database
from agent.platform.chats import ChatStore
from agent.platform import warnings


@pytest.mark.asyncio
async def test_pg_group_reset_preserves_history_isolates_and_deduplicates(tmp_path):
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='resetall:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    store = ChatStore(tmp_path,db=db)
    try:
        for group, uid in ((-100,22),(-100,33),(-200,22)):
            await store.aadd_warning(group,uid,moderator_id=11,reason='keep')
        assert await warnings.reset_group(store,-100,actor=11,request_id=50) == 2
        assert await store.aactive_warning_count(-100,22) == 0
        assert await store.aactive_warning_count(-200,22) == 1
        await store.aadd_warning(-100,22,moderator_id=11,reason='after')
        with pytest.raises(warnings.WarningStoreError):
            await warnings.reset_group(store,-100,actor=11,request_id=50)
        assert await store.aactive_warning_count(-100,22) == 1
        async with db._pool.acquire() as conn:
            assert await conn.fetchval('SELECT cleared FROM agent_warning_group_resets WHERE tenant=$1',db.scope) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_handler_requires_confirmation_and_permissions(tmp_path):
    import test_moderation as fixtures
    from agent.modules import moderation
    ctx = fixtures.ctx.__wrapped__(tmp_path)
    command = moderation.build(ctx)[1]['resetallwarns']
    from unittest.mock import patch
    with patch('agent.platform.warnings.reset_group',AsyncMock(return_value=3)) as reset:
        await command(fixtures.FakeClient(caller=fixtures.ADMIN), fixtures.FakeMessage('/resetallwarns'))
        await command(fixtures.FakeClient(caller=fixtures.MEMBER), fixtures.FakeMessage('/resetallwarns confirm'))
        reset.assert_not_awaited()
        item = fixtures.FakeMessage('/resetallwarns confirm')
        await command(fixtures.FakeClient(caller=fixtures.ADMIN),item)
        reset.assert_awaited_once_with(ctx.chats,item.chat.id,actor=11,request_id=item.id)


@pytest.mark.asyncio
async def test_pg_reset_rollback_and_concurrent_add(tmp_path):
    import json
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='resetall:'+uuid.uuid4().hex,required=True)
    assert await db.connect()
    store = ChatStore(tmp_path,db=db)
    try:
        await store.aadd_warning(-100,22,moderator_id=11,reason='before')
        async with db._pool.acquire() as conn:
            await conn.execute('INSERT INTO agent_member_warnings VALUES($1,-100,33,$2::jsonb)',db.scope,'{}')
        with pytest.raises(warnings.WarningStoreError):
            await warnings.reset_group(store,-100,actor=11,request_id=1)
        assert await store.aactive_warning_count(-100,22) == 1
        async with db._pool.acquire() as conn:
            assert await conn.fetchval('SELECT count(*) FROM agent_warning_group_resets WHERE tenant=$1',db.scope) == 0
            await conn.execute('DELETE FROM agent_member_warnings WHERE tenant=$1 AND user_id=33',db.scope)
        await asyncio.gather(warnings.reset_group(store,-100,actor=11,request_id=1),store.aadd_warning(-100,22,moderator_id=11,reason='concurrent'))
        async with db._pool.acquire() as conn:
            raw = await conn.fetchval('SELECT payload FROM agent_member_warnings WHERE tenant=$1 AND user_id=22',db.scope)
        history = json.loads(raw) if isinstance(raw,str) else raw
        assert len(history) == 2 and {w['reason'] for w in history} == {'before','concurrent'}
        assert sum(bool(w['active']) for w in history) <= 1
    finally:
        await db.close()
