"""Useful intent search stays within selected, registered command metadata."""
from agent.ui.theme import Theme
from agent.ui.workers import lookup, search_screen


def test_search_finds_descriptions_but_not_other_tools_or_inactive_commands():
    theme = Theme(worker_plugins=('encoder',))
    active = {'encode', 'compress', 'mediainfo', 'rename', 'ask'}
    screen = lookup('smaller', None, theme, active=active)
    assert '/compress' in screen.rich_text
    assert 'name matches first' in screen.rich_text
    assert '/rename' not in lookup('file', None, theme, active=active).rich_text
    assert '/compress' not in lookup('smaller', None, theme, active=active - {'compress'}).rich_text
    assert 'No matching commands' in lookup('smaller', None, theme, active=None).rich_text
    assert 'meiko' not in screen.rich_text.lower()


def test_search_ranks_name_before_description_and_preserves_exact_lookup(monkeypatch):
    theme = Theme(worker_plugins=('encoder',))
    active = {'encode', 'compress', 'mediainfo'}
    from agent.platform.menu import DESCRIPTIONS
    monkeypatch.setitem(DESCRIPTIONS, 'compress', 'Alternative encode workflow')
    screen = search_screen(None, theme, 'encode', active=active)
    details = [b.callback_data for row in screen.keyboard.inline_keyboard for b in row if (b.callback_data or '').startswith('worker:cmd:')]
    assert details == []
    assert screen.rich_text.index('<code>/encode</code>') < screen.rich_text.index('<code>/compress</code>')
    assert '/encode' in screen.rich_text
    direct = lookup('encode', None, theme, active=active)
    assert 'Command details' in direct.rich_text
    assert 'Find a command' not in direct.rich_text
    # Case variants normalize before matching, without widening discovery.
    assert '/mediainfo' in lookup('PROBE', None, theme, active=active).rich_text
