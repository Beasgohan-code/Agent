"""Shared settings require staff; ordinary members can still preview media."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import renamer
from agent.platform.attachments import CAPTION_KEY, THUMB_KEY
from agent.platform.voice import VoiceUnavailable
from test_attachments import make_ctx, FakeMessage
from test_music_controls import wire, invoke
from test_player_card import press, OWNER, FakeClient


@pytest.mark.parametrize('command', ['/setcaption new', '/setthumb', '/delthumb', '/autorename {title}'])
def test_nonadmins_cannot_mutate_shared_media_settings(tmp_path, monkeypatch, command):
    ctx = make_ctx(tmp_path)
    ctx.chats.put(-100, CAPTION_KEY, 'keep')
    ctx.chats.put(-100, THUMB_KEY, 'keep-ref')
    check = AsyncMock(return_value=False)
    monkeypatch.setattr(renamer, 'is_moderator', check)
    request = FakeMessage(command, chat_id=-100)
    asyncio.run(renamer.build(ctx)[1][command.split()[0][1:]](None, request))
    assert 'administrators' in request.replies[-1]
    assert ctx.chats.get(-100, CAPTION_KEY) == 'keep'
    assert ctx.chats.get(-100, THUMB_KEY) == 'keep-ref'
    assert ctx.chats.get(-100, renamer.TEMPLATE_KEY) is None


def test_admin_can_update_group_caption(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(renamer, 'is_moderator', AsyncMock(return_value=True))
    request = FakeMessage('/setcaption {filename}', chat_id=-100)
    asyncio.run(renamer.build(ctx)[1]['setcaption'](None, request))
    assert ctx.chats.get(-100, CAPTION_KEY) == '{filename}'


def test_group_template_view_remains_available_without_admin_check(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    check = AsyncMock(return_value=False)
    monkeypatch.setattr(renamer, 'is_moderator', check)
    request = FakeMessage('/autorename', chat_id=-100)
    asyncio.run(renamer.build(ctx)[1]['autorename'](None, request))
    check.assert_not_awaited()
    assert 'Auto-rename template' in request.replies[-1]


@pytest.mark.parametrize('command', ['setcaption', 'setthumb', 'delthumb', 'autorename', 'rename', 'testrename', 'clean', 'viewthumb', 'viewcaption'])
def test_anonymous_media_identity_refused(tmp_path, command):
    ctx = make_ctx(tmp_path)
    request = FakeMessage('/' + command)
    request.from_user = None
    asyncio.run(renamer.build(ctx)[1][command](None, request))
    assert 'personal Telegram' in request.replies[-1]


def test_thumbnail_errors_do_not_echo_telegram_references(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.chats.put(77, THUMB_KEY, 'private-ref')
    client = SimpleNamespace(send_photo=AsyncMock(side_effect=RuntimeError('private-ref bot-token')))
    request = FakeMessage('/viewthumb')
    asyncio.run(renamer.build(ctx)[1]['viewthumb'](client, request))
    assert 'private-ref' not in request.replies[-1] and 'bot-token' not in request.replies[-1]


@pytest.mark.parametrize('action', ['skip', 'stop', 'pause'])
def test_music_buttons_do_not_claim_success_or_echo_engine_secrets(tmp_path, monkeypatch, action):
    ctx, _, handlers = wire(tmp_path, monkeypatch)
    asyncio.run(invoke(handlers, '/play current'))
    failure = AsyncMock(side_effect=VoiceUnavailable('secret-url bot-token'))
    if action == 'pause':
        ctx.voice.pause = failure
    else:
        ctx.voice.leave = failure
    query = press(ctx, action, user_id=OWNER, client=FakeClient(staff=(OWNER,)))
    text = query.answers[-1][0]
    assert 'not confirmed' in text
    assert 'secret-url' not in text and 'bot-token' not in text
    assert 'left the voice chat' not in text.lower()
