"""Discoverability only suggests registered commands and real routes."""

from agent.ui.screens import help_lookup_screen, welcome_screen, info_screen, SCREENS
from agent.ui.theme import Theme


def test_short_category_name_opens_music():
    screen = help_lookup_screen("music", None, Theme(), active={"play", "queue"})
    assert "/play" in screen.rich_text
    assert "No command or section" not in screen.rich_text


def test_partial_command_finds_available_matches():
    screen = help_lookup_screen("encod", None, Theme(), active={"encode", "help"})
    assert "/encode" in screen.rich_text
    assert "help:command:encode" in [
        b.callback_data for row in screen.keyboard.inline_keyboard for b in row
    ]


def test_search_never_suggests_disabled_commands():
    screen = help_lookup_screen("encod", None, Theme(), active={"help"})
    assert "/encode" not in screen.rich_text


def test_search_bounds_and_escapes_input():
    screen = help_lookup_screen("<bad>" * 1000, None, Theme(), active={"help"})
    assert len(screen.rich_text) < 2000
    assert "<bad>" not in screen.rich_text


def test_home_shortcuts_are_live_and_have_real_routes():
    screen = welcome_screen(None, Theme(), active={"play", "encode", "help"})
    routes = [
        b.callback_data
        for row in screen.keyboard.inline_keyboard
        for b in row
        if b.callback_data
    ]
    assert routes == ["menu:help"]
    assert {b.url for row in screen.keyboard.inline_keyboard for b in row if b.url} == {"https://t.me/ouchro", "https://t.me/Godgohan"}
    assert all(route in SCREENS for route in routes)
    hidden = welcome_screen(None, Theme(), active={"help"})
    assert not any(
        b.callback_data in {"help:music-voice-chat", "help:encoding-files"}
        for row in hidden.keyboard.inline_keyboard
        for b in row
    )


def test_profile_does_not_confuse_entitlements_or_claim_no_storage():
    screen = info_screen(None, Theme())
    assert "Telegram Premium" in screen.rich_text
    assert "Meiko Premium" in screen.rich_text
    assert "Nothing is stored" not in screen.rich_text
