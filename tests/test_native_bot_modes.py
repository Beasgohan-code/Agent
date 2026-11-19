"""Native modes must not acquire command privileges or export credentials."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatJoinRequestQueryResult
from pyrogram.handlers import GuestMessageHandler, ManagedBotUpdatedHandler

from agent.modules.core import extra_handlers, guest_help, managed_bot_notice
from agent.modules.security import queue_guard_request


def test_native_handlers_are_separate_update_types():
    handlers = extra_handlers(NS())
    assert isinstance(handlers[0], GuestMessageHandler)
    assert isinstance(handlers[1], ManagedBotUpdatedHandler)


@pytest.mark.parametrize('text', ['/start secret-link', '/ban 11', '/clone token', 'hello'])
def test_guest_only_answers_native_query(text):
    async def run():
        client = NS(answer_guest_query=AsyncMock())
        await guest_help(client, NS(guest_query_id='123', text=text, chat=NS(id=-123)))
        args = client.answer_guest_query.await_args
        assert args.args == ('123',)
        content = args.kwargs['result'].input_message_content.message_text
        assert 'help only' in content
        assert 'secret-link' not in content
        assert 'token' not in content
    asyncio.run(run())


def test_non_guest_is_ignored():
    asyncio.run(guest_help(NS(), NS(text='/help')))


def test_guard_queues_only_native_queries():
    async def run():
        client = NS(answer_chat_join_request_query=AsyncMock())
        await queue_guard_request(client, NS(query_id='123'))
        client.answer_chat_join_request_query.assert_awaited_once_with(
            '123', ChatJoinRequestQueryResult.QUEUE)
        await queue_guard_request(NS(), NS(query_id=None))
    asyncio.run(run())


def test_guard_failure_is_not_retried_as_approve_or_decline():
    async def run():
        client = NS(answer_chat_join_request_query=AsyncMock(side_effect=RuntimeError('failed')))
        with pytest.raises(RuntimeError):
            await queue_guard_request(client, NS(query_id='123'))
        assert client.answer_chat_join_request_query.await_count == 1
    asyncio.run(run())


def test_managed_event_is_private_notice_not_credential_import():
    async def run():
        client = NS(send_message=AsyncMock())
        await managed_bot_notice(client, NS(user=NS(id=22, is_bot=False), bot=NS(id=33, is_bot=True)))
        args = client.send_message.await_args
        assert args.args[0] == 22
        assert '33' in args.args[1]
        assert 'No credentials were imported' in args.args[1]
    asyncio.run(run())


@pytest.mark.parametrize('user,bot', [
    (NS(id=-1), NS(id=33, is_bot=True)),
    (NS(id=True), NS(id=33, is_bot=True)),
    (NS(id=22, is_bot=True), NS(id=33, is_bot=True)),
    (NS(id=22), NS(id=33, is_bot=False)),
    (None, None),
])
def test_invalid_managed_identity_is_ignored(user, bot):
    asyncio.run(managed_bot_notice(NS(), NS(user=user, bot=bot)))


def test_guard_has_local_deadline(monkeypatch):
    async def run():
        observed = []
        async def deadline(awaitable, *, timeout):
            observed.append(timeout)
            awaitable.close()
            raise asyncio.TimeoutError
        monkeypatch.setattr(asyncio, 'wait_for', deadline)
        client = NS(answer_chat_join_request_query=AsyncMock())
        with pytest.raises(asyncio.TimeoutError):
            await queue_guard_request(client, NS(query_id='123'))
        assert observed == [8]
    asyncio.run(run())


def test_native_reply_failure_has_no_public_fallback():
    async def run():
        client = NS(answer_guest_query=AsyncMock(side_effect=RuntimeError('failed')))
        with pytest.raises(RuntimeError):
            await guest_help(client, NS(guest_query_id='123'))
        assert client.answer_guest_query.await_count == 1
    asyncio.run(run())
