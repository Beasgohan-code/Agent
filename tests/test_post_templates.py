"""Confirmed Post Maker settings writes and read-through isolation."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.platform.db import Database
from agent.platform.post_templates import PostTemplates
from agent.modules import postmaker
from test_plugins import make_ctx, FakeMessage


def test_configured_database_failure_does_not_fall_back(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.db = SimpleNamespace(connected=False, _pool=None, scope='test')
        _, commands = postmaker.build(ctx)
        client = SimpleNamespace(send_message=AsyncMock())
        for command in ['posttemplate', 'postpreview', 'post']:
            request = FakeMessage('/' + command + (' title | body' if command != 'posttemplate' else ''))
            await commands[command](client, request)
            assert 'unavailable' in request.replies[-1].lower()
        request = FakeMessage('/posttemplate <i>{body}</i>')
        await commands['posttemplate'](client, request)
        assert 'not confirmed' in request.replies[-1]
        assert ctx.chats.get(-1001234567890, 'post_template') is None
        client.send_message.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv('AGENT_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_real_postgres_restart_scope_and_authoritative_reads():
    async def scenario():
        scope = 'post-template-test:' + uuid.uuid4().hex
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope)
        other = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope + ':clone')
        try:
            assert await db.connect() and await other.connect()
            service = PostTemplates(db)
            assert await service.get(-100, 'legacy') == 'legacy'
            await service.set(-100, 'first')
            assert await service.get(-100, 'stale') == 'first'
            assert await service.get(-200, 'other group') == 'other group'
            assert await PostTemplates(other).get(-100, 'clone default') == 'clone default'
            await db.close()
            assert await db.connect()
            assert await service.get(-100, 'default') == 'first'
            await service.set(-100, '<b>{title}</b>\n\n{body}')
            assert await service.get(-100, 'first') == '<b>{title}</b>\n\n{body}'
            with pytest.raises(ValueError):
                await service.set(-100, 'x'*601)
            assert len(await service.get(-100, '')) < 601
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_post_templates WHERE tenant=$1 OR tenant=$2', scope, scope + ':clone')
            await db.close()
            await other.close()
    asyncio.run(scenario())
