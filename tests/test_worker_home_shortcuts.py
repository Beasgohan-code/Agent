"""Worker landing actions copy only current selected commands, never execute."""
from agent.ui.theme import Theme
from agent.ui.workers import overview, availability_screen


def copies(screen):
    return [b.copy_text.text for row in screen.keyboard.inline_keyboard for b in row if b.copy_text]


def test_home_shortcuts_follow_active_selected_tools_without_controller_credit():
    theme = Theme(worker_plugins=('encoder',))
    home = overview(None, theme, active={'encode', 'compress', 'mediainfo', 'ask', 'ban'})
    assert copies(home) == ['/encode', '/compress']
    assert 'Copying does not run' in home.rich_text
    assert 'meiko' not in home.rich_text.lower()
    assert all(len(row) <= 2 for row in home.keyboard.inline_keyboard)
    assert copies(overview(None, theme, active={'mediainfo', 'ask'})) == ['/mediainfo']
    assert copies(overview(None, theme, active=None)) == []
    assert copies(overview(None, theme, active=set())) == []
    assert copies(overview(None, theme, active={'encode'}, help_mode=True)) == []


def test_multi_tool_shortcuts_and_availability_links_are_current():
    theme = Theme(worker_plugins=('encoder', 'ai_agent'))
    home = overview(None, theme, active={'encode', 'compress', 'ask'})
    assert copies(home) == ['/encode', '/ask']
    available = availability_screen(None, theme, active={'encode'})
    data = [b.callback_data for row in available.keyboard.inline_keyboard for b in row]
    assert 'worker:encoder:0' in data
    assert 'worker:ai_agent:0' not in data
    assert 'worker:moderation:0' not in data
    assert all(len(row) <= 2 for row in available.keyboard.inline_keyboard)
    unknown = availability_screen(None, theme, active=None)
    assert not any((b.callback_data or '').endswith(':0') for row in unknown.keyboard.inline_keyboard for b in row)
