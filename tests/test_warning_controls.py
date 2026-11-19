"""New warning removal commands reuse the authoritative member warning store."""
import asyncio
import test_moderation as fixtures
from agent.modules import moderation


def test_warning_remove_and_reset_preserve_history(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, handlers = moderation.build(ctx)
        client = fixtures.FakeClient(caller=fixtures.ADMIN)
        for _ in range(2):
            await ctx.chats.aadd_warning(fixtures.FakeMessage('').chat.id, 22, moderator_id=11,reason='test')
        for name, expected in (('rmwarn',1),('resetwarn',0)):
            item = fixtures.FakeMessage('/'+name,reply=True)
            await handlers[name](client,item)
            assert await ctx.chats.aactive_warning_count(item.chat.id,22) == expected
        assert len(ctx.chats._member(item.chat.id,22)['warnings']) == 2
        assert all(not row['active'] for row in ctx.chats._member(item.chat.id,22)['warnings'])
    asyncio.run(scenario())


def test_warning_removal_denied_caller_cannot_clear(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        item = fixtures.FakeMessage('/resetwarn',reply=True)
        await ctx.chats.aadd_warning(item.chat.id,22,moderator_id=11,reason='test')
        await moderation.build(ctx)[1]['resetwarn'](fixtures.FakeClient(caller=fixtures.MEMBER),item)
        assert await ctx.chats.aactive_warning_count(item.chat.id,22) == 1
    asyncio.run(scenario())


def test_pg_warning_removal_is_scoped_and_history_retained(tmp_path):
    import os, uuid, json, pytest
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'],scope='warning-controls:'+uuid.uuid4().hex,required=True)
        assert await db.connect()
        try:
            ctx = fixtures.ctx.__wrapped__(tmp_path)
            ctx.db = db
            ctx.chats = ChatStore(tmp_path,db=db)
            item = fixtures.FakeMessage('/resetwarn',reply=True)
            await ctx.chats.aadd_warning(item.chat.id,22,moderator_id=11,reason='test')
            await ctx.chats.aadd_warning(item.chat.id,33,moderator_id=11,reason='other')
            await moderation.build(ctx)[1]['resetwarn'](fixtures.FakeClient(caller=fixtures.ADMIN),item)
            assert await ctx.chats.aactive_warning_count(item.chat.id,22) == 0
            assert await ctx.chats.aactive_warning_count(item.chat.id,33) == 1
            async with db._pool.acquire() as conn:
                payload = await conn.fetchval('SELECT payload FROM agent_member_warnings WHERE tenant=$1 AND user_id=22', db.scope)
            rows = json.loads(payload) if isinstance(payload,str) else payload
            assert len(rows) == 1 and not rows[0]['active'] and rows[0]['cleared_at']
        finally:
            await db.close()
    asyncio.run(scenario())


def test_resetrules_uses_authoritative_writer_and_guard(tmp_path, monkeypatch):
    import test_group as group_fixtures
    from agent.modules import group
    from unittest.mock import AsyncMock
    async def scenario():
        ctx = group_fixtures.ctx.__wrapped__(tmp_path)
        writer = AsyncMock()
        monkeypatch.setattr('agent.platform.group_rules.save_rules',writer)
        command = group.build(ctx)[1]['resetrules']
        await command(group_fixtures.FakeClient(caller=group_fixtures.MEMBER),group_fixtures.FakeMessage('/resetrules'))
        writer.assert_not_awaited()
        await command(group_fixtures.FakeClient(),group_fixtures.FakeMessage('/resetrules'))
        writer.assert_awaited_once_with(ctx,group_fixtures.CHAT,'',actor=11)
    asyncio.run(scenario())
