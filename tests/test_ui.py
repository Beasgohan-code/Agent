"""Screen construction, theming and HTML safety."""

import asyncio

import pytest
from pyrogram.enums import ParseMode
from pyrogram.parser import Parser

from agent.ui.keyboards import CB_HELP, CB_HOME, CB_INFO
from agent.health import HealthMonitor
from agent.ui.screens import (
    format_uptime,
    help_screen,
    info_screen,
    ping_screen,
    welcome_screen,
)
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
    assert "Meiko" in screen.rich_text
    assert "Try" in screen.rich_text                 # three commands to start from
    # Menu navigation remains available without source promotion.
    assert [c for c in callbacks(screen.keyboard) if c] == [CB_HELP]
    urls = [b.url for row in screen.keyboard.inline_keyboard for b in row if b.url]
    assert urls == ["https://t.me/ouchro", "https://t.me/ouchro", "https://t.me/Godgohan"]
    assert not any("github.com" in url for url in urls)


def test_the_start_screen_fits_a_caption():
    """It is sent as the caption of the /start picture, capped at 1024."""
    from agent.utils.sender import _visible_text, to_safe_html

    active = {"start", "help", "ping", "fsave", "leech"}
    screen = welcome_screen(make_user(), Theme(), active=active)
    text = to_safe_html(screen.rich_text)

    assert len(_visible_text(text)) < 1024
    assert "Commands" in text             # counted from the live registry
    assert "5" in text


def test_welcome_screen_without_a_first_name_still_greets():
    screen = welcome_screen(make_user(first_name=""), Theme())

    assert "Hello" in screen.rich_text
    assert "Ada" not in screen.rich_text


def test_help_screen_is_an_overview_that_links_to_sections_and_back():
    screen = help_screen(make_user(), Theme())

    assert screen.rich_text.startswith("<h2>")
    assert "Help</h2>" in screen.rich_text
    assert "<table" in screen.rich_text               # a real rich table
    assert "Essentials" in screen.rich_text          # a section row
    assert "/about" not in screen.rich_text          # no bibliography
    assert CB_HOME in callbacks(screen.keyboard)
    assert "help:essentials" in callbacks(screen.keyboard)


def test_a_help_section_lists_its_commands_with_descriptions():
    from agent.ui.screens import _section_builder

    screen = _section_builder("Essentials")(make_user(), Theme())

    assert "/start" in screen.rich_text
    assert "/help" in screen.rich_text
    assert "Open the main menu" in screen.rich_text
    assert "help:all" in callbacks(screen.keyboard)


def test_an_unavailable_plugin_is_not_in_the_help():
    from agent.ui.screens import _section_builder

    active = {"start", "help", "ping", "status"}
    music = _section_builder("Music (voice chat)")(make_user(), Theme(), active=active)

    assert "/play" not in music.rich_text
    assert "Nothing in this section" in music.rich_text


def test_help_with_a_command_name_opens_that_commands_page():
    from agent.ui.screens import help_lookup_screen

    screen = help_lookup_screen("/encode", make_user(), Theme(), active={"encode", "start"})

    assert screen.rich_text.startswith("<h2>/encode</h2>")
    assert "<table" in screen.rich_text
    assert "Encoding &amp; files" in screen.rich_text      # the section it belongs to
    assert "help:encoding-files" in callbacks(screen.keyboard)
    assert "help:all" in callbacks(screen.keyboard)


def test_help_with_a_command_from_a_switched_off_plugin_says_so():
    from agent.ui.screens import help_lookup_screen

    screen = help_lookup_screen("play", make_user(), Theme(), active={"start", "help"})

    assert "switched off" in screen.rich_text
    assert "help:music-voice-chat" not in callbacks(screen.keyboard)


def test_help_with_a_section_name_opens_the_section():
    from agent.ui.screens import help_lookup_screen

    screen = help_lookup_screen("moderation", make_user(), Theme(), active=None)

    assert "/ban" in screen.rich_text
    assert "<table" in screen.rich_text


def test_the_help_command_routes_an_argument_to_the_lookup():
    """``/help encode`` must not silently ignore the word after the command."""
    from agent.handlers.commands import CommandHandlers

    class Sender:
        def __init__(self):
            self.sent = []

        async def send(self, chat_id, screen):
            self.sent.append(screen.rich_text)

    sender = Sender()
    handlers = CommandHandlers(sender, Theme(), active_commands=lambda: ["encode", "start"])
    message = FakeUser(text="/help encode", from_user=make_user(), chat=FakeUser(id=-100))

    asyncio.run(handlers.help(None, message))

    assert len(sender.sent) == 1
    assert sender.sent[0].startswith("<h2>/encode</h2>")


def test_help_with_an_unknown_name_is_not_a_dead_end():
    from agent.ui.screens import help_lookup_screen

    screen = help_lookup_screen("nonsense", make_user(), Theme(), active=None)

    assert "No command or section called" in screen.rich_text
    assert "help:all" in callbacks(screen.keyboard)


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
    from agent.ui.screens import HELP_SECTIONS, _section_builder

    builders = [welcome_screen, help_screen, info_screen]
    builders += [_section_builder(title) for _icon, title, _cmds in HELP_SECTIONS]
    for builder in builders:
        rendered = to_safe_html(builder(make_user(), Theme()).rich_text)
        assert 0 < len(rendered) < 4096, builder


# --- theme / premium emoji -------------------------------------------------


def test_theme_uses_unicode_when_no_custom_ids_are_configured():
    theme = Theme({})

    assert theme.emoji("wave") == "\U0001f44b"
    assert "<tg-emoji" not in theme.emoji("wave")
    assert theme.custom_emoji_enabled is False


def test_the_shipped_theme_carries_real_premium_ids():
    theme = Theme()

    assert theme.custom_emoji_enabled is True
    assert 'emoji-id="5084979757905347540"' in theme.emoji("check")
    # Glyphs without a vetted id stay unicode rather than render broken.
    assert "<tg-emoji" not in theme.emoji("wave")


def test_premium_emoji_can_be_switched_off(monkeypatch):
    import importlib

    from agent.ui import premium

    monkeypatch.setenv("USE_PREMIUM_EMOJI", "0")
    try:
        importlib.reload(premium)
        assert premium.premium_enabled() is False
        assert premium.emoji_table()[1] == {}
    finally:
        monkeypatch.delenv("USE_PREMIUM_EMOJI", raising=False)
        importlib.reload(premium)


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


# --- ping screen -----------------------------------------------------------


def test_ping_screen_reports_live_health():
    monitor = HealthMonitor()
    monitor.record_success(latency_ms=37)
    monitor.record_activity("start")

    screen = ping_screen(monitor, Theme())

    assert "healthy" in screen.rich_text
    assert "37 ms" in screen.rich_text
    assert "Probes" in screen.rich_text
    assert CB_HOME in callbacks(screen.keyboard)


def test_ping_screen_survives_a_dead_link():
    monitor = HealthMonitor(failure_threshold=2)
    monitor.record_failure("ConnectionResetError: link down")
    monitor.record_failure("ConnectionResetError: link down")

    screen = ping_screen(monitor, Theme())

    assert "down" in screen.rich_text
    assert "link down" in screen.rich_text


def test_ping_screen_without_a_monitor():
    screen = ping_screen(None, Theme())

    assert "not running" in screen.rich_text


@pytest.mark.parametrize(
    "seconds,expected",
    [(5, "5s"), (65, "1m 5s"), (3725, "1h 2m 5s"), (90000, "1d 1h 0m")],
)
def test_uptime_is_human_readable(seconds, expected):
    assert format_uptime(seconds) == expected


def test_ping_screen_renders_to_parseable_html():
    monitor = HealthMonitor()
    monitor.record_success(latency_ms=12)

    rendered = to_safe_html(ping_screen(monitor, Theme()).rich_text)

    assert "<h2>" not in rendered
    parsed = asyncio.run(Parser(None).parse(rendered, ParseMode.HTML))
    assert parsed["message"].strip()


def test_help_copy_is_user_facing_not_deployment_instructions():
    from agent.ui.screens import HELP_SECTIONS, help_section_screen

    screens = [help_screen(make_user(), Theme())]
    screens += [help_section_screen(title, make_user(), Theme()) for _, title, _ in HELP_SECTIONS]
    for screen in screens:
        assert 'OWNER_ID' not in screen.rich_text
        assert 'group commands need moderator rights' not in screen.rich_text
        assert 'command(s) ready here' not in screen.rich_text
    assert 'Choose a category' in screens[0].rich_text
    essentials = help_section_screen('Essentials', make_user(), Theme())
    assert 'owner-only ones need' not in essentials.rich_text
