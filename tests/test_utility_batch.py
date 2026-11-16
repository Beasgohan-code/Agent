"""Utility batch: safe identity, timezone validation and rich rendering."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_groups
from test_groups import FakeClient, FakeMessage, MEMBER
from agent.modules import utilities


@pytest.fixture
def ctx(tmp_path):
    return test_groups.ctx.__wrapped__(tmp_path)


@pytest.mark.parametrize('command', ['id', 'info', 'repo'])
def test_no_argument_utilities_reject_ignored_input(ctx, command):
    async def scenario():
        request = FakeMessage('/' + command + ' extra')
        await utilities.build(ctx)[1][command](FakeClient(), request)
        assert 'Usage' in request.replies[-1]
    asyncio.run(scenario())


def test_world_clock_validates_and_renders_named_zone(ctx):
    async def scenario():
        handler = utilities.build(ctx)[1]['time']
        for name in ['Asia/Kolkata', 'UTC', 'Europe/London']:
            request = FakeMessage('/time ' + name)
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await handler(None, request)
            body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
            assert name in body and '<table' in body and '<tg-emoji' in body
            if name == 'Asia/Kolkata':
                assert '+0530' in body
        for arg in ['Not/A_Zone', '../etc/passwd', 'UTC extra', '<script>']:
            request = FakeMessage('/time ' + arg)
            await handler(None, request)
            assert 'Unknown timezone' in request.replies[-1] or 'Usage' in request.replies[-1]
            assert '<script>' not in request.replies[-1]
    asyncio.run(scenario())


def test_sender_chat_is_not_inferred_to_be_caller(ctx):
    async def scenario():
        commands = utilities.build(ctx)[1]
        request = FakeMessage('/info')
        request.reply_to_message = SimpleNamespace(from_user=None, sender_chat=SimpleNamespace(id=-123))
        await commands['info'](FakeClient(), request)
        assert 'no visible user identity' in request.replies[-1]
        request = FakeMessage('/id')
        request.from_user = None
        request.sender_chat = SimpleNamespace(id=-987)
        await commands['id'](FakeClient(), request)
        assert '-987' in request.replies[-1] and 'not proof' in request.replies[-1]
    asyncio.run(scenario())


def test_moderation_metadata_hidden_from_non_moderators(ctx):
    async def scenario():
        ctx.chats.add_warning(-100900, 22, moderator_id=11, reason='private reason')
        target = SimpleNamespace(id=22, first_name='<unsafe>', last_name=None, username=None)
        handler = utilities.build(ctx)[1]['info']
        request = FakeMessage('/info', target=target)
        await handler(FakeClient(caller=MEMBER), request)
        assert 'Warnings:' not in request.replies[-1]
        assert '&lt;unsafe&gt;' in request.replies[-1]
        request = FakeMessage('/info', target=target)
        await handler(FakeClient(), request)
        assert 'Warnings: 1' in request.replies[-1]
        assert 'private reason' not in request.replies[-1]
    asyncio.run(scenario())


def test_legacy_repo_command_does_not_publish_repository_links(ctx):
    async def scenario():
        request = FakeMessage('/repo')
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await utilities.build(ctx)[1]['repo'](None, request)
        call = request._client.send_rich_message.await_args.kwargs
        body = call['rich_text'].html
        assert '<table' in body and '&lt;code&gt;' not in body
        assert 'github.com' not in body
        assert 'Source links are not published' in body
        assert all(not button.url for row in call['reply_markup'].inline_keyboard for button in row)
    asyncio.run(scenario())


def test_public_navigation_has_no_source_links():
    from agent.ui.keyboards import home_keyboard, help_keyboard, nav_keyboard, info_keyboard
    for keyboard in (home_keyboard(), help_keyboard(), nav_keyboard(), info_keyboard(99)):
        for row in keyboard.inline_keyboard:
            for button in row:
                assert not button.url
                assert 'source' not in button.text.lower()
