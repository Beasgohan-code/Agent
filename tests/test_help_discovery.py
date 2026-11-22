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


def test_help_has_dedicated_blacklist_federation_and_welcome_modules():
    from agent.ui.screens import help_screen
    active = {'blocklist', 'addblocklist', 'blocklistmode', 'welcome', 'setwelcome', 'newfed', 'fedinfo'}
    screen = help_screen(None, Theme(), active=active)
    routes = [b.callback_data for row in screen.keyboard.inline_keyboard for b in row]
    for slug in ('blacklist', 'federations', 'welcome-goodbye'):
        assert 'help:' + slug in routes
        assert 'help:' + slug in SCREENS


def test_blacklist_module_help_documents_real_syntax_not_unsupported_example_commands():
    screen = help_lookup_screen('blacklist', None, Theme(), active={'blocklist', 'addblocklist', 'rmblocklist', 'blocklistmode', 'blocklistdelete'})
    text = screen.rich_text
    assert '/addblocklist' in text and '(spam rude)' in text
    assert 'Automatic detection' in text and 'approved' in text
    assert 'nothing' in text and 'tban' in text and 'tmute' in text
    assert '/addblacklist' not in text and '/blsticker' not in text
    assert 'Examples' in text


def test_welcome_and_federation_module_help_explain_scope_and_limits():
    from agent.ui.screens import help_section_screen
    welcome = help_section_screen('Welcome & goodbye', None, Theme(), active={'setwelcome', 'welcome', 'goodbye'})
    assert '{mention}' in welcome.rich_text and '/welcome on' in welcome.rich_text
    federation = help_section_screen('Federations', None, Theme(), active={'newfed', 'joinfed', 'chatfed'})
    assert '/newfed' in federation.rich_text and 'chat owner' in federation.rich_text
    assert 'Ban synchronization is not available' in federation.rich_text


def test_feature_help_examples_do_not_advertise_unregistered_commands():
    screen = help_lookup_screen('blacklist', None, Theme(), active={'blocklist'})
    assert '/addblocklist' not in screen.rich_text
    assert '/blocklistmode' not in screen.rich_text
    assert '/blocklist' in screen.rich_text


def test_feature_help_commands_have_one_home_and_fit_message_limits():
    from agent.ui.screens import HELP_SECTIONS, MODULE_HELP, HELP_PAGE_SIZE, help_section_screen
    from agent.utils.sender import to_safe_html, _visible_text
    for title in MODULE_HELP:
        commands = next(commands for _, section, commands in HELP_SECTIONS if section == title)
        for command in commands:
            assert sum(command in items for _, _, items in HELP_SECTIONS) == 1
        for page in range((len(commands) + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE):
            screen = help_section_screen(title, None, Theme(), active=set(commands), page=page)
            assert len(_visible_text(to_safe_html(screen.rich_text)).encode('utf-16-le')) // 2 < 4000
            for row in screen.keyboard.inline_keyboard:
                for button in row:
                    assert button.callback_data in SCREENS
