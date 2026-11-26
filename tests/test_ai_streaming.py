"""Streaming answer deltas and cosmetic draft failures, entirely offline."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from agent.modules import ai_agent


class Content:
    def __init__(self, raw):
        self.raw = raw

    async def iter_chunked(self, size):
        # Exercise split UTF-8 characters, SSE JSON and CRLF boundaries.
        for start in range(0, len(self.raw), 3):
            yield self.raw[start:start + 3]


def event(delta):
    return ('data: ' + json.dumps({'choices': [{'delta': delta}]}, ensure_ascii=False) + '\r\n\r\n').encode()


def test_stream_only_exposes_answer_text_and_requires_done():
    async def scenario():
        update = AsyncMock()
        raw = event({'reasoning_content': 'not public'}) + event({'content': 'Hi 😀'}) + event({'content': ' <b>'})
        answer = await ai_agent.read_stream(Content(raw + b'data: [DONE]\n\n'), update)
        assert answer == 'Hi 😀 <b>'
        assert update.await_count == 2
        assert update.await_args.args == ('Hi 😀 <b>',)
        with pytest.raises(ai_agent.AIUnavailable, match='interrupted'):
            await ai_agent.read_stream(Content(raw), update)
        with pytest.raises(ai_agent.AIUnavailable, match='safety limit'):
            await ai_agent.read_stream(Content(b'x' * 65537), update)
    asyncio.run(scenario())


def test_rich_drafts_throttle_escape_and_preserve_topic(monkeypatch):
    async def scenario():
        clock = [1.0]
        monkeypatch.setattr(ai_agent.time, 'monotonic', lambda: clock[0])
        client = NS(send_rich_message_draft=AsyncMock())
        draft = ai_agent.AnswerDraft(client, NS(chat=NS(id=-100), message_thread_id=7))
        await draft.update()
        assert 'tg-thinking' in client.send_rich_message_draft.await_args.kwargs['rich_text'].html
        await draft.update('too soon')
        assert client.send_rich_message_draft.await_count == 1
        clock[0] += 2
        await draft.update('<b>😀')
        kwargs = client.send_rich_message_draft.await_args.kwargs
        assert '&lt;b&gt;' in kwargs['rich_text'].html
        assert kwargs['message_thread_id'] == 7
        assert kwargs['draft_id'] == draft.draft_id
        client.send_rich_message_draft.side_effect = RuntimeError('transport')
        clock[0] += 2
        await draft.update('failure')
        assert not draft.enabled
    asyncio.run(scenario())


def test_plain_draft_for_older_clients():
    async def scenario():
        client = NS(send_message_draft=AsyncMock())
        await ai_agent.AnswerDraft(client, NS(chat=NS(id=22))).update('hello')
        assert 'hello' in client.send_message_draft.await_args.kwargs['text']
    asyncio.run(scenario())


def test_ask_streams_but_only_sends_one_final_reply(monkeypatch):
    async def scenario():
        async def provider(key, model, question, on_delta=None):
            assert on_delta is not None
            await on_delta('partial')
            return 'final answer'
        monkeypatch.setattr(ai_agent, 'complete', provider)
        client = NS(send_rich_message_draft=AsyncMock())
        request = NS(text='/ask hello', from_user=NS(id=22), chat=NS(id=22), reply=AsyncMock())
        _, commands = ai_agent.build(NS(settings=NS(ai_api_key='test', ai_model='test')))
        await commands['ask'](client, request)
        request.reply.assert_awaited_once()
        assert 'final answer' in request.reply.await_args.args[0]
        client.send_rich_message_draft.assert_awaited_once()
    asyncio.run(scenario())


def test_provider_enables_sse_only_for_streaming_request(monkeypatch):
    from test_ai_agent import Response, Session

    async def scenario():
        response = Response()
        response.content = Content(event({'content': 'streamed'}) + b'data: [DONE]\n\n')
        session = Session(response)
        monkeypatch.setattr(ai_agent.aiohttp, 'ClientSession', lambda **kwargs: session)
        update = AsyncMock()
        assert await ai_agent.complete('secret', 'model', 'question', on_delta=update) == 'streamed'
        assert session.calls[0][1]['json']['stream'] is True
        update.assert_awaited_once_with('streamed')
    asyncio.run(scenario())


def test_draft_failure_does_not_block_answer_or_retry_provider(monkeypatch):
    async def scenario():
        provider = AsyncMock(return_value='answer')
        monkeypatch.setattr(ai_agent, 'complete', provider)
        client = NS(send_rich_message_draft=AsyncMock(side_effect=RuntimeError('unsupported')))
        request = NS(text='/ask hello', from_user=NS(id=22), chat=NS(id=22), reply=AsyncMock())
        _, commands = ai_agent.build(NS(settings=NS(ai_api_key='test', ai_model='test')))
        await commands['ask'](client, request)
        provider.assert_awaited_once_with('test', 'test', 'hello')
        request.reply.assert_awaited_once()
    asyncio.run(scenario())
