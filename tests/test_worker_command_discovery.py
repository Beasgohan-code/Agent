import pytest
from agent.ui.theme import Theme
from agent.ui.workers import lookup, callback, plugin_screen


def test_partial_help_finds_only_live_selected_commands():
    theme = Theme(worker_plugins=('encoder',))
    screen = lookup('comp', None, theme, active={'compress', 'encode', 'clone', 'plans'})
    assert '/compress' in screen.rich_text
    assert '/clone' not in screen.rich_text
    assert '/plans' not in screen.rich_text
    assert 'worker:cmd:compress' in str(screen.keyboard)


def test_typo_help_offers_live_match_without_running_it():
    screen = lookup('compres', None, Theme(worker_plugins=('encoder',)), active={'compress'})
    assert '/compress' in screen.rich_text
    assert 'worker:cmd:compress' in str(screen.keyboard)


def test_command_details_copy_and_callback_revalidate_scope():
    theme = Theme(worker_plugins=('encoder',))
    screen = callback('worker:cmd:compress', None, theme, active={'compress'})
    assert screen is not None
    buttons = [b for row in screen.keyboard.inline_keyboard for b in row]
    assert any(b.copy_text and b.copy_text.text == '/compress' for b in buttons)
    assert callback('worker:cmd:compress', None, theme, active=set()) is None
    assert callback('worker:cmd:clone', None, theme, active={'clone'}) is None
    assert callback('worker:cmd:compress', None, Theme(), active={'compress'}) is None


def test_command_page_has_tappable_details():
    screen = plugin_screen(None, Theme(worker_plugins=('encoder',)), 'encoder', active={'compress', 'encode'})
    assert 'worker:cmd:compress' in str(screen.keyboard)
    assert 'worker:cmd:encode' in str(screen.keyboard)


@pytest.mark.parametrize('query', ['plans', 'clone', '<script>', 'zzzzzzzz'])
def test_unknown_or_controller_help_has_no_hidden_command_details(query):
    screen = lookup(query, None, Theme(worker_plugins=('encoder',)), active={'encode', 'plans', 'clone'})
    assert '/plans' not in screen.rich_text
    assert '/clone' not in screen.rich_text
    assert '<script>' not in screen.rich_text


def test_details_back_button_restores_command_page():
    from agent.ui.workers import commands, PAGE_SIZE
    from agent.modules import MODULES
    active = {c for module in MODULES for c in module.MANIFEST.commands}
    theme = Theme(worker_plugins=())
    command = commands('moderation', active)[PAGE_SIZE]
    screen = callback(f'worker:cmd:{command}', None, theme, active=active)
    assert 'worker:moderation:1' in str(screen.keyboard)


def test_forged_command_payload_and_stale_search_reject():
    theme = Theme(worker_plugins=('encoder',))
    for payload in ('worker:cmd:compress:extra', 'worker:cmd:<script>', 'worker:cmd:COMPRESS'):
        assert callback(payload, None, theme, active={'compress'}) is None
    result = lookup('compres', None, theme, active={'encode'})
    assert '/compress' not in result.rich_text
