"""Premium accents are decorative and preserve navigation/fallback behavior."""
import pytest
from agent.ui.theme import Theme
from agent.ui.workers import overview, plugin_screen, about_screen, profile_screen, lookup
from agent.modules import MODULES


@pytest.mark.parametrize('custom', [True, False])
def test_all_worker_navigation_is_consistently_accented(custom):
    theme = Theme(worker_plugins=('encoder',)) if custom else Theme({}, worker_plugins=('encoder',))
    active = {c for m in MODULES for c in m.MANIFEST.commands}
    screens = [overview(None, theme, active=active), overview(None, theme, active=active, help_mode=True),
               plugin_screen(None, theme, 'moderation', active=active, page=1),
               about_screen(None, theme, active=active), profile_screen(None, theme, active=active),
               lookup('encode', None, theme, active=active)]
    for screen in screens:
        assert 'Meiko' not in screen.rich_text
        for row in screen.keyboard.inline_keyboard:
            assert len(row) <= 2
            for button in row:
                assert button.style is not None
                assert bool(button.callback_data) != bool(button.copy_text)
                if button.callback_data:
                    assert len(button.callback_data.encode()) <= 64
                else:
                    assert button.copy_text.text in {'/encode', '/compress'}
                assert '<tg-emoji' not in button.text
                if custom:
                    assert button.icon_custom_emoji_id
                else:
                    assert button.icon_custom_emoji_id is None
                    assert not button.text[0].isascii()


def test_theme_button_respects_explicit_styles_and_unknown_icon():
    from pyrogram.enums import ButtonStyle
    b = Theme().button('Remove', icon='trash', callback_data='safe:confirm', style=ButtonStyle.DANGER)
    assert b.style == ButtonStyle.DANGER
    assert b.icon_custom_emoji_id is None
    assert b.callback_data == 'safe:confirm'


@pytest.mark.parametrize('rich', [True, False])
def test_rejected_button_icons_fall_back_without_mutating_original(rich):
    import asyncio
    from types import SimpleNamespace
    from agent.ui.screens import Screen
    from agent.utils.sender import ScreenSender
    from pyrogram.types import InlineKeyboardMarkup
    theme = Theme()
    keyboard = InlineKeyboardMarkup([[theme.button('Help', icon='question', callback_data='menu:help')]])
    calls = []
    async def send(**kwargs):
        calls.append(kwargs)
        if kwargs['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id:
            raise RuntimeError('CUSTOM_EMOJI_INVALID')
        return SimpleNamespace(id=5)
    client = SimpleNamespace(send_message=send)
    if rich:
        client.send_rich_message = send
    sender = ScreenSender(client, theme)
    result = asyncio.run(sender.send(5, Screen('<h2>Help</h2>', keyboard)))
    assert result.id == 5
    assert len(calls) == 2
    assert keyboard.inline_keyboard[0][0].icon_custom_emoji_id  # Source keyboard is immutable to retry.
    assert not calls[-1]['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id
    assert calls[-1]['reply_markup'].inline_keyboard[0][0].callback_data == 'menu:help'


def test_edit_rejected_button_icon_falls_back_once():
    import asyncio
    from types import SimpleNamespace
    from agent.ui.screens import Screen
    from agent.utils.sender import ScreenSender
    from pyrogram.types import InlineKeyboardMarkup
    calls = []
    async def edit(**kwargs):
        calls.append(kwargs)
        if kwargs['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id:
            raise RuntimeError('CUSTOM_EMOJI_INVALID')
    theme = Theme()
    screen = Screen('<h2>Tools</h2>', InlineKeyboardMarkup([[theme.button('Help', icon='question', callback_data='menu:help')]]))
    sender = ScreenSender(SimpleNamespace(send_rich_message=lambda: None), theme)
    assert asyncio.run(sender.edit(SimpleNamespace(edit_message_text=edit), screen)) is True
    assert len(calls) == 2
    assert not calls[-1]['reply_markup'].inline_keyboard[0][0].icon_custom_emoji_id
