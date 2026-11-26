"""Use supplied document IDs, keep action fields and Unicode recovery intact."""
from agent.ui.theme import Theme
from agent.ui.keyboards import start_keyboard, nav_keyboard
from agent.ui.screens import Screen
from agent.utils.sender import _plain_screen


def test_supplied_ids_used_in_text_and_buttons():
    theme = Theme()
    assert theme.emoji_id('add') == '5039891861246838069'
    assert theme.emoji_id('support') == '5040036030414062506'
    assert theme.emoji_id('download') == '5877307202888273539'
    assert '5040033797031070992' in theme.emoji('wave')
    buttons = [b for row in start_keyboard('ExampleBot',theme=theme).inline_keyboard for b in row]
    assert [b.icon_custom_emoji_id for b in buttons] == [theme.emoji_id(name) for name in ('add','help','support','updates','crown')]
    assert [b.text for b in buttons] == ['Add me','Help','Support','Updates','Owner']
    assert buttons[0].url == 'https://t.me/ExampleBot?startgroup=true'
    assert buttons[1].callback_data == 'menu:help'


def test_custom_start_icons_fallback_once_without_losing_urls():
    theme = Theme()
    keyboard = start_keyboard('ExampleBot',theme=theme)
    plain = _plain_screen(Screen('Welcome',keyboard),theme)
    buttons = [b for row in plain.keyboard.inline_keyboard for b in row]
    assert all(not b.icon_custom_emoji_id for b in buttons)
    assert buttons[0].text == '➕ Add me'
    assert buttons[2].url == 'https://t.me/ouchro'
    assert _plain_screen(plain,theme).keyboard.inline_keyboard[0][0].text == '➕ Add me'


def test_disabled_theme_retains_readable_navigation():
    theme = Theme({})
    buttons = [b for row in start_keyboard('ExampleBot',theme=theme).inline_keyboard for b in row]
    assert buttons[1].text == '💡 Help'
    assert all(not b.icon_custom_emoji_id for b in buttons)
    assert nav_keyboard(theme=theme).inline_keyboard[0][0].text == '🏡 Menu'
