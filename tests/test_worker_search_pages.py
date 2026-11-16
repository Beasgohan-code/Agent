"""Worker search pages preserve selection/live availability and bounded callbacks."""
from agent.ui.theme import Theme
from agent.ui.workers import lookup, callback, discoverable
from agent.modules import MODULES


def test_worker_search_paginates_current_available_matches():
    theme = Theme(worker_plugins=('moderation',))
    active = {c for module in MODULES for c in module.MANIFEST.commands}
    candidates = sorted(c for c in discoverable(theme, active) if 'set' in c)
    assert len(candidates) > 6
    first = lookup('set', None, theme, active=active)
    # Search callbacks re-evaluate the same term on each page.
    import base64
    encoded = base64.urlsafe_b64encode(b'set').decode().rstrip('=')
    first = callback(f'worker:find:0:{encoded}', None, theme, active=active)
    assert first is not None
    keys = [b for row in first.keyboard.inline_keyboard for b in row]
    next_data = next(b.callback_data for b in keys if b.text.endswith('Next'))
    second = callback(next_data, None, theme, active=active)
    assert second is not None
    assert any(c in second.rich_text for c in candidates[6:12])
    assert 'Previous' in str(second.keyboard)
    assert all(len(b.callback_data.encode()) <= 64 for b in keys if b.callback_data)
    assert all(len(row) <= 2 for row in second.keyboard.inline_keyboard)
    reduced = active - set(candidates[6:])
    assert callback(next_data, None, theme, active=reduced) is None
    assert 'meiko' not in first.rich_text.lower()


def test_worker_search_rejects_malformed_and_cross_tool_pages():
    theme = Theme(worker_plugins=('encoder',))
    for data in ('worker:find:-1:YmFu', 'worker:find:0:_', 'worker:find:0:====', 'worker:find:9999:YmFu'):
        assert callback(data, None, theme, active={'encode'}) is None
    screen = callback('worker:find:0:YXNr', None, theme, active={'encode', 'ask'})
    assert screen is not None
    assert '/ask' not in screen.rich_text
    assert 'No matching commands' in screen.rich_text
