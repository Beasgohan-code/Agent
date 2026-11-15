"""Keep the existing offline preview synchronized with actual screen builders."""
from pathlib import Path

from tools.render_ui_preview import render_preview


def test_ui_preview_is_reproducible_and_describes_optin_ai():
    rendered = render_preview()
    assert Path('docs/UI_PREVIEW.md').read_text() == rendered
    assert '💎 Meiko' in rendered
    assert 'Commands  9' in rendered
    assert '/autochat on|off|status' in rendered
    assert 'AI Agent  2 registered' in rendered
    assert 'This is not a Telegram screenshot' in rendered
    assert 'no message text stored' not in rendered
    assert not any(line.endswith(' ') for line in rendered.splitlines())
