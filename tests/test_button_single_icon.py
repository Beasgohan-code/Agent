"""Premium button icons and Unicode fallback must never render together."""
from pyrogram.types import InlineKeyboardMarkup
from agent.ui.theme import Theme, EMOJI_FALLBACKS
from agent.ui.screens import Screen
from agent.utils.sender import _plain_screen


def test_premium_has_clean_label_and_unicode_fallback_exactly_once():
    theme = Theme()
    button = theme.button('Commands', icon='search', callback_data='safe:commands')
    assert button.icon_custom_emoji_id
    assert button.text == 'Commands'
    screen = Screen('Tools', InlineKeyboardMarkup([[button]]))
    plain = _plain_screen(screen, theme)
    fallback = plain.keyboard.inline_keyboard[0][0]
    assert fallback.text == f'{EMOJI_FALLBACKS["search"]} Commands'
    assert fallback.icon_custom_emoji_id is None
    assert _plain_screen(plain, theme).keyboard.inline_keyboard[0][0].text == fallback.text
    assert button.text == 'Commands' and button.icon_custom_emoji_id
    assert fallback.callback_data == button.callback_data


def test_plain_theme_unknown_icon_and_custom_mapping():
    plain = Theme({}).button('Start', icon='bolt', callback_data='start')
    assert plain.text == f'{EMOJI_FALLBACKS["bolt"]} Start'
    unknown = Theme().button('Action', icon='not_an_icon', callback_data='safe')
    assert unknown.text == 'Action' and unknown.icon_custom_emoji_id is None
    theme = Theme({'search': 12345})
    button = theme.button('Find', icon='search', callback_data='find')
    theme.disable_custom_emoji()
    fallback = _plain_screen(Screen('Tools', InlineKeyboardMarkup([[button]])), theme)
    assert fallback.keyboard.inline_keyboard[0][0].text == f'{EMOJI_FALLBACKS["search"]} Find'
