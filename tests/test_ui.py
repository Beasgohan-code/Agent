"""Screen construction, theming and HTML safety."""

import asyncio

import pytest
from pyrogram.enums import ParseMode
from pyrogram.parser import Parser

from agent.ui.keyboards import CB_HELP, CB_HOME, CB_INFO
from agent.ui.screens import help_screen, info_screen, welcome_screen
from agent.ui.theme import Theme, strip_custom_emoji
from agent.utils.sender import to_safe_html


class FakeUser:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def make_user(**overrides):
    data = {
        "id": 123456789,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "username": "ada",
        "language_code": "en",
        "is_premium": False,
    }
    data.update(overrides)
    return FakeUser(**data)


def callbacks(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


# --- screens ---------------------------------------------------------------


def test_welcome_screen_greets_the_user_and_shows_the_menu():
    screen = welcome_screen(make_user(), Theme())

    assert "Ada Lovelace" in screen.rich_text
    assert "Agent" in screen.rich_text
    assert callbacks(screen.keyboard) == [CB_HELP, CB_INFO]


def test_welcome_screen_without_a_first_name_still_greets():
    screen = welcome_screen(make_user(first_name=""), Theme())

    assert "Hello" in screen.rich_text
    assert "Ada" not in screen.rich_text


def test_help_screen_lists_commands_and_links_back():
    screen = help_screen(make_user(), Theme())

    assert "/start" in screen.rich_text
    assert "/help" in screen.rich_text
    assert CB_HOME in callbacks(screen.keyboard)


def test_info_screen_shows_telegram_profile_fields():
    screen = info_screen(make_user(), Theme())

    assert "Ada Lovelace" in screen.rich_text
    assert "@ada" in screen.rich_text
    assert "123456789" in screen.rich_text
    assert CB_HOME in callbacks(screen.keyboard)


def test_info_screen_tolerates_missing_optional_fields():
    user = FakeUser(id=42, first_name="Solo")

    screen = info_screen(user, Theme())

    assert "Solo" in screen.rich_text
    assert "not set" in screen.rich_text


def test_user_supplied_text_is_escaped():
    screen = welcome_screen(make_user(first_name="<script>alert(1)</script>", last_name=""), Theme())

    assert "<script>" not in screen.rich_text
    assert "&lt;script&gt;" in screen.rich_text


def test_every_screen_fits_a_telegram_message():
    for builder in (welcome_screen, help_screen, info_screen):
        rendered = to_safe_html(builder(make_user(), Theme()).rich_text)
        assert 0 < len(rendered) < 4096


# --- theme / premium emoji -------------------------------------------------


def test_theme_uses_unicode_when_no_custom_ids_are_configured():
    theme = Theme()

    assert theme.emoji("wave") == "\U0001f44b"
    assert "<tg-emoji" not in theme.emoji("wave")
    assert theme.custom_emoji_enabled is False


def test_theme_upgrades_known_names_to_custom_emoji():
    theme = Theme({"wave": 5368324170671202286})

    markup = theme.emoji("wave")
    assert markup == '<tg-emoji emoji-id="5368324170671202286">\U0001f44b</tg-emoji>'
    assert theme.custom_emoji_enabled is True


def test_theme_ignores_unknown_names():
    theme = Theme({"not_a_glyph": 123})

    assert theme.custom_emoji_enabled is False
    assert theme.emoji("not_a_glyph") == ""


def test_theme_can_fall_back_after_a_rejection():
    theme = Theme({"wave": 123})

    theme.disable_custom_emoji()

    assert theme.emoji("wave") == "\U0001f44b"


def test_strip_custom_emoji_keeps_the_unicode_character():
    text = '<b>Hi</b> <tg-emoji emoji-id="42">\u2728</tg-emoji>'

    assert strip_custom_emoji(text) == "<b>Hi</b> \u2728"


# --- rich -> standard HTML -------------------------------------------------


@pytest.mark.parametrize("builder", [welcome_screen, help_screen, info_screen])
def test_rendered_html_has_no_rich_only_tags(builder):
    rendered = to_safe_html(builder(make_user(), Theme()).rich_text)
    lowered = rendered.lower()

    for tag in ("<h1", "<h2", "<h3", "<table", "<details", "<footer", "<hr", "<tg-button"):
        assert tag not in lowered


@pytest.mark.parametrize("builder", [welcome_screen, help_screen, info_screen])
def test_rendered_html_is_parseable_by_the_telegram_parser(builder):
    rendered = to_safe_html(builder(make_user(), Theme()).rich_text)

    parsed = asyncio.run(Parser(None).parse(rendered, ParseMode.HTML))

    assert parsed["message"].strip()
    assert parsed["message"] == parsed["message"].strip()
