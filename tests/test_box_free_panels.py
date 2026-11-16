"""Native Richgram layout, never a truncated box-drawing fallback."""
import asyncio
from types import SimpleNamespace

import pytest

from agent.ui import tables
from agent.utils import rich

BOXES = set('┌┬┐├┼┤└┴┘─│')


@pytest.fixture(autouse=True)
def restore_rich_mode():
    previous = tables.rich_enabled()
    yield
    tables.set_rich(previous)


@pytest.mark.parametrize('native', [True, False])
def test_panel_never_draws_boxes_or_truncates_values(native):
    previous = tables.rich_enabled()
    try:
        tables.set_rich(native)
        value = 'No encryption key configured — contact the deployment owner'
        body = tables.panel('Clone encryption', table=tables.kv_table([
            ('Status', value), ('Other commands', 'No encryption key needed for other commands')]))
        for rendered in (str(body), body.classic):
            assert not BOXES.intersection(rendered)
            assert '<pre>' not in rendered
            assert value in rendered
        if native:
            assert '<h2>' in body and '<table' in body
        else:
            assert '<b>' in body and '<table' not in body
    finally:
        tables.set_rich(previous)


def test_raw_native_table_fallback_preserves_labels_values_and_escaping():
    body = tables.Table(headers=('Name', 'Meaning'), rows=(('<script>', 'a & b'),)).rich_block()
    result = rich.classic(body)
    assert not BOXES.intersection(result)
    assert '<pre>' not in result and '<table' not in result
    assert 'Name' in result and 'Meaning' in result
    assert '&lt;script&gt;' in result and 'a &amp; b' in result


def test_missing_key_screen_keeps_encryption_guard_and_no_box(tmp_path):
    from test_clone import build, FakeMessage, MEMBER

    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard = ctx.clone_setup
        wizard.store._box = SimpleNamespace(enabled=False)
        message = FakeMessage('/clone')
        await wizard.begin(message)
        text = str(message.replies)
        assert not BOXES.intersection(text)
        assert 'encryption' in text.lower()
        assert 'not your BotFather token' in text
        assert wizard.active(MEMBER) is None
    asyncio.run(scenario())
