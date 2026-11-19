"""Screen-level retries must not turn ambiguous delivery into duplicate posts."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.ui import tables
from agent.ui.screens import Screen
from agent.ui.theme import Theme
from agent.utils.sender import ScreenSender


@pytest.fixture(autouse=True)
def rich_mode():
    tables.set_rich(True)
    yield
    tables.set_rich(True)


def client():
    return SimpleNamespace(send_rich_message=AsyncMock(), send_message=AsyncMock(), send_photo=AsyncMock())


@pytest.mark.parametrize('operation', ['send', 'photo', 'edit'])
@pytest.mark.parametrize('error', [TimeoutError('ambiguous'), RuntimeError('FLOOD_WAIT_10'), RuntimeError('CHAT_WRITE_FORBIDDEN')])
def test_no_retries_for_transient_or_permission_errors(operation, error):
    c = client()
    theme = Theme()
    sender = ScreenSender(c, theme)
    keyboard = object()
    screen = Screen('<h2>Menu</h2><tg-emoji emoji-id="123">✨</tg-emoji>', keyboard)
    if operation == 'send':
        c.send_rich_message.side_effect = error
        with pytest.raises(type(error)):
            asyncio.run(sender.send(1, screen))
        c.send_message.assert_not_awaited()
        assert c.send_rich_message.await_count == 1
    elif operation == 'photo':
        c.send_photo.side_effect = error
        with pytest.raises(type(error)):
            asyncio.run(sender.send_photo(1, screen, 'image'))
        c.send_rich_message.assert_not_awaited()
        c.send_message.assert_not_awaited()
    else:
        query = SimpleNamespace(_client=c, edit_message_text=AsyncMock(side_effect=error))
        assert asyncio.run(sender.edit(query, screen)) is None
        assert query.edit_message_text.await_count == 1
    assert tables.rich_enabled()


def test_explicit_rich_rejection_keeps_keyboard():
    c = client()
    c.send_rich_message.side_effect = RuntimeError('RICH_TEXT_INVALID')
    keyboard = object()
    asyncio.run(ScreenSender(c, Theme()).send(1, Screen('<h2>Menu</h2>', keyboard)))
    assert c.send_message.await_args.kwargs['reply_markup'] is keyboard
    assert '<h2>' not in c.send_message.await_args.kwargs['text']
    assert tables.rich_enabled()


def test_explicit_emoji_rejection_retries_unicode_with_keyboard():
    c = client()
    c.send_message.side_effect = [RuntimeError('CUSTOM_EMOJI_INVALID'), SimpleNamespace(id=1)]
    keyboard = object()
    asyncio.run(ScreenSender(c, Theme()).send(1, Screen('<tg-emoji emoji-id="123">✨</tg-emoji>', keyboard)))
    assert c.send_message.await_count == 2
    second = c.send_message.await_args.kwargs
    assert '<tg-emoji' not in second['text'] and '✨' in second['text']
    assert second['reply_markup'] is keyboard


def test_plain_emoji_send_timeout_does_not_retry():
    c = client()
    c.send_message.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        asyncio.run(ScreenSender(c, Theme()).send(1, Screen('<tg-emoji emoji-id="123">✨</tg-emoji>')))
    assert c.send_message.await_count == 1


def test_rejected_photo_falls_back_to_text():
    c = client()
    c.send_photo.side_effect = RuntimeError('WEBPAGE_CURL_FAILED')
    asyncio.run(ScreenSender(c, Theme()).send_photo(1, Screen('<b>Welcome</b>'), 'bad-image'))
    c.send_message.assert_awaited_once()


def test_caption_budget_decodes_entities():
    c = client()
    asyncio.run(ScreenSender(c, Theme()).send_photo(1, Screen('&amp;' * 1000), 'image'))
    c.send_photo.assert_awaited_once()
    c.send_message.assert_not_awaited()


def test_caption_budget_counts_astral_characters_as_utf16():
    c = client()
    asyncio.run(ScreenSender(c, Theme()).send_photo(1, Screen('😁' * 513), 'image'))
    c.send_photo.assert_not_awaited()
    c.send_message.assert_awaited_once()


@pytest.mark.parametrize('rich_rejected',[False,True])
def test_ephemeral_screen_keeps_receiver_through_format_fallback(rich_rejected):
    c=client()
    if rich_rejected:c.send_rich_message.side_effect=RuntimeError('RICH_MESSAGE_UNSUPPORTED')
    screen=Screen('<h2>Private navigation</h2>',object())
    asyncio.run(ScreenSender(c,Theme()).send(-100,screen,receiver_user_id=22))
    call=c.send_message.await_args if rich_rejected else c.send_rich_message.await_args
    assert call.kwargs['ephemeral_message_parameters'].receiver_user_id==22


def test_ephemeral_navigation_uses_private_edit_and_never_public_replacement():
    c=client()
    c.edit_ephemeral_message_text=AsyncMock(return_value=SimpleNamespace(id=7))
    query=SimpleNamespace(_client=c,from_user=SimpleNamespace(id=22),
        message=SimpleNamespace(chat=SimpleNamespace(id=-100),receiver_user=SimpleNamespace(id=22),ephemeral_message_id=7),
        edit_message_text=AsyncMock())
    sender=ScreenSender(c,Theme())
    assert asyncio.run(sender.edit(query,Screen('<h2>Help</h2>',object()))) is True
    c.edit_ephemeral_message_text.assert_awaited_once()
    query.edit_message_text.assert_not_awaited()
    assert c.edit_ephemeral_message_text.await_args.kwargs['receiver_id']==22
    query.from_user.id=33
    assert asyncio.run(sender.edit(query,Screen('<h2>Help</h2>',object()))) is None
    assert c.edit_ephemeral_message_text.await_count==1


def test_failed_ephemeral_send_never_retries_as_public():
    c=client()
    c.send_rich_message.side_effect=TimeoutError()
    with pytest.raises(TimeoutError):
        asyncio.run(ScreenSender(c,Theme()).send(-100,Screen('<h2>Private</h2>',object()),receiver_user_id=22))
    c.send_message.assert_not_awaited()
    c.send_photo.assert_not_awaited()


def test_missing_ephemeral_acknowledgement_does_not_resend():
    c=client()
    c.send_rich_message.return_value=None
    with pytest.raises(RuntimeError,match='unconfirmed'):
        asyncio.run(ScreenSender(c,Theme()).send(-100,Screen('<h2>Private</h2>',object()),receiver_user_id=22))
    c.send_message.assert_not_awaited()
