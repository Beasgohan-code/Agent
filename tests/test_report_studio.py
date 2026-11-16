"""Report review, strict mutations and escaped owner notifications."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import reports
from agent.modules.reports.queue import _notify_owner
from test_plugins import make_ctx, FakeMessage, CHAT, OWNER


def test_paged_queue_details_and_closed_review(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        for i in range(25):
            ctx.chats.add_report(CHAT, reporter_id=OWNER, reason=f'<reason{i}>')
        _, commands = reports.build(ctx)
        async def read(text):
            request = FakeMessage(text)
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands['reports'](None, request)
            return request._client.send_rich_message.await_args.kwargs['rich_text'].html
        body = await read('/reports 3')
        assert 'Page <b>3/3</b>' in body and '#25' in body and '#1<' not in body
        body = await read('/reports show 1')
        assert '&lt;reason0&gt;' in body and '<reason0>' not in body
        assert 'visible to this chat' in body and '<tg-emoji' in body
        await read('/reports close 1')
        body = await read('/reports closed')
        assert '#1' in body and '1 closed' in body
        ctx.chats.add_report(CHAT - 1, reporter_id=OWNER, reason='OTHER_GROUP_SECRET')
        assert 'OTHER_GROUP_SECRET' not in await read('/reports show 1')
        assert ctx.chats.reports(CHAT, limit=0) == []
    asyncio.run(scenario())


@pytest.mark.parametrize('text', ['/reports close 1 extra', '/reports close 0', '/reports close ١',
                                  '/reports close ' + '9'*5000, '/reports unknown', '/reports show -1'])
def test_malformed_review_does_not_close(tmp_path, text):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.add_report(CHAT, reporter_id=OWNER, reason='keep open')
        _, commands = reports.build(ctx)
        request = FakeMessage(text)
        await commands['reports'](None, request)
        assert len(ctx.chats.reports(CHAT)) == 1
        assert 'Use' in request.replies[-1] or 'Usage' in request.replies[-1]
    asyncio.run(scenario())


def test_notification_escapes_member_text_and_identifies_chat():
    async def scenario():
        client = SimpleNamespace(send_message=AsyncMock())
        request = FakeMessage('/appeal')
        result = await _notify_owner(client, OWNER, request, 1, '<b>fake admin</b> & text')
        body = client.send_message.await_args.args[1]
        assert '&lt;b&gt;fake admin&lt;/b&gt;' in body and '<b>fake admin</b>' not in body
        assert str(CHAT) in body and result == 'The owner was notified.'
        client.send_message.side_effect = RuntimeError('SECRET_PROVIDER_TOKEN')
        assert 'SECRET_PROVIDER_TOKEN' not in await _notify_owner(client, OWNER, request, 1, 'text')
    asyncio.run(scenario())


def test_personal_identity_and_moderator_checks(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        _, commands = reports.build(ctx)
        for name, handler in commands.items():
            request = FakeMessage('/' + name)
            request.from_user = None
            await handler(None, request)
            assert 'personal Telegram' in request.replies[-1]
        client = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        request = FakeMessage('/reports show 1', uid=99)
        await commands['reports'](client, request)
        assert 'Only moderators' in request.replies[-1]
    asyncio.run(scenario())
