"""Bounded, group-scoped filter management without changing matching policy."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_groups
from agent.modules import filters
from test_groups import FakeClient, FakeMessage


@pytest.fixture
def ctx(tmp_path):
    return test_groups.ctx.__wrapped__(tmp_path)


def test_multiline_preview_escaping_and_delete_metadata(ctx):
    async def scenario():
        _, commands = filters.build(ctx)
        client = FakeClient()
        await commands['filter'](client, FakeMessage('/filter hello first\n\n<b>second</b>'))
        assert ctx.chats.filters(-100900)['hello'] == 'first\n\n<b>second</b>'
        from agent.ui.tables import set_rich
        set_rich(True)
        request = FakeMessage('/filters show hello')
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await commands['filters'](client, request)
        body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
        assert '&lt;b&gt;second&lt;/b&gt;' in body and '<b>second</b>' not in body
        assert '<table' in body and '<tg-emoji' in body
        await commands['stopfilter'](client, FakeMessage('/stopfilter hello extra'))
        assert 'hello' in ctx.chats.filters(-100900)
        await commands['stopfilter'](client, FakeMessage('/stopfilter hello'))
        assert 'hello' not in ctx.chats.filters(-100900)
        assert 'hello' not in ctx.chats.settings(-100900).get('filter_authors', {})
    asyncio.run(scenario())


def test_filter_limit_allows_updates_and_refuses_truncation(ctx):
    async def scenario():
        for i in range(100):
            ctx.chats.set_filter(-100900, f'key{i:03d}', 'old', by=11)
        _, commands = filters.build(ctx)
        await commands['filter'](FakeClient(), FakeMessage('/filter overflow nope'))
        assert 'overflow' not in ctx.chats.filters(-100900)
        await commands['filter'](FakeClient(), FakeMessage('/filter key000 updated'))
        assert ctx.chats.filters(-100900)['key000'] == 'updated'
        await commands['filter'](FakeClient(), FakeMessage('/filter key000 ' + 'x'*2001))
        assert ctx.chats.filters(-100900)['key000'] == 'updated'
    asyncio.run(scenario())


def test_pagination_identity_and_group_isolation(ctx):
    async def scenario():
        for i in range(23):
            ctx.chats.set_filter(-100900, f'key{i:02d}', f'answer{i:02d}', by=11)
        ctx.chats.set_filter(-200, 'SECRET_OTHER_GROUP', 'other', by=11)
        _, commands = filters.build(ctx)
        request = FakeMessage('/filters 3')
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await commands['filters'](FakeClient(), request)
        body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
        assert 'Page <b>3/3</b>' in body and 'key22' in body
        assert 'key00' not in body and 'SECRET_OTHER_GROUP' not in body
        for text in ['/filters 0', '/filters -1', '/filters ١', '/filters 1 extra', '/filters show']:
            request = FakeMessage(text)
            await commands['filters'](FakeClient(), request)
            assert 'Use' in request.replies[-1]
        for name, handler in commands.items():
            request = FakeMessage('/' + name)
            request.from_user = None
            await handler(FakeClient(), request)
            assert 'personal Telegram' in request.replies[-1]
    asyncio.run(scenario())
