"""Bounded link creation and token-free paginated management."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import linkshare
from test_plugins import make_ctx, FakeMessage, OWNER


def stored(ctx, tmp_path):
    path = tmp_path / 'payload'
    path.write_text('content')
    return ctx.storage.save_path(OWNER, path, name='entry.txt')


@pytest.mark.parametrize('numbers', ['0', '721', '1 1001', '1 2 3', '-1', '١', '9'*5000])
def test_limits_rejected_without_creating_link(tmp_path, numbers):
    async def scenario():
        ctx = make_ctx(tmp_path)
        file = stored(ctx, tmp_path)
        _, commands = linkshare.build(ctx)
        request = FakeMessage(f'/share {file.id} {numbers}')
        await commands['share'](None, request)
        assert ctx.links.owned(OWNER) == []
        assert request.replies
    asyncio.run(scenario())


def test_all_link_pages_hide_tokens_and_other_owners(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        file = stored(ctx, tmp_path)
        records = [ctx.links.create(file.id, OWNER, ttl_hours=i + 1) for i in range(23)]
        ctx.links.create(file.id, 99, ttl_hours=6)
        _, commands = linkshare.build(ctx)
        for page in range(1, 4):
            request = FakeMessage(f'/links {page}')
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands['links'](None, request)
            body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
            assert f'Page <b>{page}/3</b>' in body and '<table' in body
            assert '<b>23</b>' in body
            assert all(record.token not in body for record in records)
        request = FakeMessage('/links 4')
        await commands['links'](None, request)
        assert 'from 1 to 3' in request.replies[-1]
    asyncio.run(scenario())


def test_anonymous_and_extra_revoke_args_refused(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        file = stored(ctx, tmp_path)
        record = ctx.links.create(file.id, OWNER, ttl_hours=6)
        _, commands = linkshare.build(ctx)
        request = FakeMessage(f'/revoke {record.token} extra')
        await commands['revoke'](None, request)
        assert 'Usage' in request.replies[-1] and not record.revoked
        for name, handler in commands.items():
            request = FakeMessage('/' + name)
            request.from_user = None
            await handler(None, request)
            assert 'personal Telegram' in request.replies[-1]
    asyncio.run(scenario())


def test_share_boundary_values_and_unescaped_table_name(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        file = stored(ctx, tmp_path)
        file.name = 'A & B.txt'
        _, commands = linkshare.build(ctx)
        request = FakeMessage(f'/share {file.id} 720 1000')
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await commands['share'](SimpleNamespace(me=SimpleNamespace(username='agentbot')), request)
        record = ctx.links.owned(OWNER)[0]
        assert record.max_uses == 1000
        body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
        assert 'A &amp; B.txt' in body and 'A &amp;amp;' not in body
    asyncio.run(scenario())
