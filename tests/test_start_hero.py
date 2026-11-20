"""Rich hero delivery preserves navigation and avoids ambiguous retries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.ui import tables
from agent.ui.screens import welcome_screen, SCREENS
from agent.ui.theme import Theme
from agent.utils.sender import ScreenSender
from agent.config import DEFAULT_START_IMAGE


@pytest.fixture(autouse=True)
def enable_rich():
    tables.set_rich(True)
    yield
    tables.set_rich(True)


def client():
    return SimpleNamespace(
        send_rich_message=AsyncMock(), send_photo=AsyncMock(), send_message=AsyncMock()
    )


def test_start_uses_requested_image_default():
    assert DEFAULT_START_IMAGE == "https://files.catbox.moe/ddqcyu.jpg"


def test_hero_is_native_image_media_not_a_link_preview():
    c = client()
    screen = welcome_screen(None, Theme(), active={"help", "warn"})
    asyncio.run(ScreenSender(c, Theme()).send_hero(1, screen, "assets/agent-hero.jpg"))
    payload = c.send_rich_message.await_args.kwargs
    assert '<img src="tg://photo?id=agent_hero"' in payload["rich_text"].html
    assert payload["rich_text"].media[0].media.media == "assets/agent-hero.jpg"
    assert payload["reply_markup"] is screen.keyboard
    c.send_photo.assert_not_awaited()


def test_explicit_rich_rejection_falls_back_to_captioned_photo():
    c = client()
    c.send_rich_message.side_effect = RuntimeError("RICH_MESSAGE_UNSUPPORTED")
    asyncio.run(
        ScreenSender(c, Theme()).send_hero(1, welcome_screen(None, Theme()), "image")
    )
    c.send_photo.assert_awaited_once()
    assert "<img" not in c.send_photo.await_args.kwargs["caption"]


def test_ambiguous_hero_timeout_never_retries_as_photo():
    c = client()
    c.send_rich_message.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        asyncio.run(
            ScreenSender(c, Theme()).send_hero(
                1, welcome_screen(None, Theme()), "image"
            )
        )
    c.send_photo.assert_not_awaited()


def test_welcome_only_suggests_available_tools_and_real_callbacks():
    screen = welcome_screen(None, Theme(), active={"help", "warn"})
    assert "/leech" not in screen.rich_text
    assert "/files" not in screen.rich_text
    assert "no message text stored" not in screen.rich_text
    for row in screen.keyboard.inline_keyboard:
        for button in row:
            if button.callback_data:
                assert button.callback_data in SCREENS


def test_repeated_private_hero_uses_acknowledged_media_id():
    c=client()
    c.send_rich_message.return_value=SimpleNamespace(photo=SimpleNamespace(file_id='cached-hero-id'))
    sender=ScreenSender(c,Theme())
    screen=welcome_screen(None,Theme())
    async def scenario():
        await sender.send_hero(1,screen,'https://example.com/hero.jpg')
        await sender.send_hero(1,screen,'https://example.com/hero.jpg')
    asyncio.run(scenario())
    media=[call.kwargs['rich_text'].media[0].media.media for call in c.send_rich_message.await_args_list]
    assert media==['https://example.com/hero.jpg','cached-hero-id']


def test_cached_hero_timeout_never_retries_upload():
    c=client()
    c.send_rich_message.side_effect=[SimpleNamespace(photo=SimpleNamespace(file_id='cached-hero-id')),TimeoutError()]
    sender=ScreenSender(c,Theme())
    async def scenario():
        await sender.send_hero(1,welcome_screen(None,Theme()),'https://example.com/hero.jpg')
        with pytest.raises(TimeoutError):
            await sender.send_hero(1,welcome_screen(None,Theme()),'https://example.com/hero.jpg')
    asyncio.run(scenario())
    assert c.send_rich_message.await_count==2
    c.send_photo.assert_not_awaited()
