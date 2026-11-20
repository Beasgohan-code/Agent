"""Worker help describes actual selected manifest context without controller credits."""
import pytest
from agent.ui.theme import Theme
from agent.ui.workers import command_screen, commands
from agent.modules import MODULES


@pytest.mark.parametrize('slug,name', [('encoder', 'encode'), ('ai_agent', 'ask'), ('moderation', 'ban')])
def test_worker_command_context_matches_manifest_and_offers_guide(slug, name):
    from agent.platform.policy import GROUP_CORE
    active = {c for module in MODULES for c in module.MANIFEST.commands}
    theme = Theme(worker_plugins=(slug,))
    screen = command_screen(None, theme, name, active=active)
    assert screen is not None
    text = screen.rich_text
    eligible = GROUP_CORE if slug == 'moderation' else (slug,)
    manifest = next(m.MANIFEST for m in MODULES if m.MANIFEST.slug in eligible and name in m.MANIFEST.commands)
    assert 'Chat scope' in text and manifest.scope in text
    assert 'Permissions' in text
    for permission in manifest.permissions:
        assert permission in text
    assert 'Required credential names' in text
    assert 'not a readiness check' in text
    assert 'meiko' not in text.lower() and 'controller' not in text.lower()
    buttons = [b for row in screen.keyboard.inline_keyboard for b in row]
    assert f'worker:guide:{slug}' in [b.callback_data for b in buttons]
    assert all(len(row) <= 2 for row in screen.keyboard.inline_keyboard)
    assert command_screen(None, theme, name, active=active - {name}) is None
    assert name in commands(slug, active)


def test_worker_context_never_exposes_unselected_tool():
    theme = Theme(worker_plugins=('encoder',))
    assert command_screen(None, theme, 'ask', active={'ask', 'encode'}) is None


def test_music_context_uses_generic_storage_requirement():
    screen=command_screen(None,Theme(worker_plugins=('music',)),'play',active={'play'})
    assert screen is not None
    assert 'persistent storage' in screen.rich_text
    assert 'postgres' not in screen.rich_text.lower()
