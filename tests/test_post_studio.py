"""Post Maker publication path, bounded rendering and safe result reporting."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram.enums import ParseMode

from agent.modules import postmaker
from agent.modules.postmaker.templates import PostError, render, _post_text, DEFAULT_TEMPLATE
from test_plugins import make_ctx, FakeMessage, CHAT


def test_template_substitution_is_single_pass():
    assert render('{title}|{body}', '{body}', '<b>body</b>') == '{body}|&lt;b&gt;body&lt;/b&gt;'
    assert '<b>' in _post_text(DEFAULT_TEMPLATE, 'title', 'body')


@pytest.mark.parametrize('title,body', [('x'*201, ''), ('', 'x'*3001), ('title', '&'*1000), ('', '😀'*2200)])
def test_oversized_composition_is_rejected_not_truncated(title, body):
    with pytest.raises(PostError):
        render(DEFAULT_TEMPLATE, title, body)


def test_publish_and_preview_use_identical_payload_without_preview_audit(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.log = log = Mock()
        _, handlers = postmaker.build(ctx)
        client = SimpleNamespace(send_message=AsyncMock())
        await handlers['postpreview'](client, FakeMessage('/postpreview title | <unsafe> & body'))
        log.assert_not_called()
        preview = client.send_message.await_args
        await handlers['post'](client, FakeMessage('/post title | <unsafe> & body'))
        assert client.send_message.await_args == preview
        assert preview.args[0] == CHAT
        assert preview.kwargs['parse_mode'] == ParseMode.HTML
        assert '&lt;unsafe&gt;' in preview.args[1]
        log.assert_called_once()
        assert '<unsafe>' not in str(log.call_args)
    asyncio.run(scenario())


def test_permissions_limits_and_caption_support(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        _, handlers = postmaker.build(ctx)
        client = SimpleNamespace(send_message=AsyncMock(), get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        await handlers['post'](client, FakeMessage('/post bad | body', uid=99))
        client.send_message.assert_not_awaited()
        await handlers['postpreview'](client, FakeMessage('/postpreview t | ' + 'x'*3001))
        client.send_message.assert_not_awaited()
        request = FakeMessage('/post title', reply_to=SimpleNamespace(text=None, caption='caption & text'))
        await handlers['post'](client, request)
        assert 'caption &amp; text' in client.send_message.await_args.args[1]
    asyncio.run(scenario())


def test_send_failure_and_audit_failure_are_not_false_success(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.log = Mock()
        _, handlers = postmaker.build(ctx)
        client = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('SECRET_TOKEN')))
        request = FakeMessage('/post title | body')
        await handlers['post'](client, request)
        assert 'unconfirmed' in request.replies[-1]
        assert 'SECRET_TOKEN' not in ''.join(request.replies)
        ctx.chats.log.assert_not_called()
        client.send_message.side_effect = None
        ctx.chats.log.side_effect = RuntimeError('SECRET_DB')
        request = FakeMessage('/post title | body')
        await handlers['post'](client, request)
        assert 'Do not republish' in request.replies[-1]
        assert 'SECRET_DB' not in ''.join(request.replies)
    asyncio.run(scenario())


def test_template_reset_and_readable_untruncated_layout(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        _, handlers = postmaker.build(ctx)
        client = SimpleNamespace()
        await handlers['posttemplate'](client, FakeMessage('/posttemplate <i>{body}</i>'))
        assert ctx.chats.get(CHAT, 'post_template') == '<i>{body}</i>'
        await handlers['posttemplate'](client, FakeMessage('/posttemplate reset'))
        assert ctx.chats.get(CHAT, 'post_template') == DEFAULT_TEMPLATE
        request = FakeMessage('/posttemplate')
        await handlers['posttemplate'](client, request)
        assert '&lt;b&gt;{title}&lt;/b&gt;' in request.replies[-1]
        assert 'background' in request.replies[-1]
    asyncio.run(scenario())
