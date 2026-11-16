"""Controller welcome links never bleed into worker branding."""
import pytest
from types import SimpleNamespace as NS
from agent.ui.screens import welcome_screen
from agent.ui.theme import Theme
from pyrogram.enums import ButtonStyle


def test_main_welcome_requested_five_buttons():
    screen = welcome_screen(NS(first_name='User'), Theme(custom_emoji={}), active={'help'}, bot_username='ExampleBot')
    buttons = [b for row in screen.keyboard.inline_keyboard for b in row]
    assert len(buttons) == 5
    assert buttons[0].url == 'https://t.me/ExampleBot?startgroup=true'
    assert buttons[0].style == ButtonStyle.SUCCESS
    assert buttons[1].callback_data == 'menu:help'
    assert [b.url for b in buttons[2:]] == ['https://t.me/ouchro','https://t.me/ouchro','https://t.me/Godgohan']
    assert 'github.com' not in screen.rich_text.lower()


def test_worker_welcome_has_no_main_links():
    screen = welcome_screen(NS(first_name='User'), Theme(custom_emoji={},worker_plugins=('filestore',)), active={'genlink','batch','custom_batch'}, bot_username='CloneBot')
    buttons = [b for row in screen.keyboard.inline_keyboard for b in row]
    assert not any(getattr(b,'url',None) in ('https://t.me/ouchro','https://t.me/Godgohan') for b in buttons)


def test_unavailable_username_does_not_invent_add_link():
    screen = welcome_screen(None,Theme(custom_emoji={}),active=set(),bot_username='bad/name')
    assert not any('startgroup' in (b.url or '') for row in screen.keyboard.inline_keyboard for b in row)


@pytest.mark.asyncio
async def test_runtime_identity_cached_and_fallback():
    from unittest.mock import AsyncMock
    from agent.ui.bot_identity import bot_username
    client = NS(me=NS(username='CurrentBot'),get_me=AsyncMock())
    assert await bot_username(client) == 'CurrentBot'
    client.get_me.assert_not_awaited()
    client.me = None
    client.get_me.return_value = NS(username='FallbackBot')
    assert await bot_username(client) == 'FallbackBot'
    client.get_me.side_effect = RuntimeError('SECRET')
    assert await bot_username(client) is None
