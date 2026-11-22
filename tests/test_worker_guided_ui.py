import pytest
from agent.ui.theme import Theme
from agent.ui.workers import callback, overview, PROFILES, QUICK_START
from agent.modules import MODULES


@pytest.mark.parametrize('slug', tuple(PROFILES))
def test_each_worker_has_a_live_guided_start(slug):
    theme = Theme(worker_plugins=(slug,))
    active = {c for m in MODULES for c in m.MANIFEST.commands}
    screen = callback(f'worker:guide:{slug}', None, theme, active=active)
    assert screen is not None
    assert 'Get started' in screen.rich_text
    assert 'Meiko' not in screen.rich_text
    copied = [b.copy_text.text for row in screen.keyboard.inline_keyboard for b in row if b.copy_text]
    assert copied
    assert all(text.lstrip('/') in active for text in copied)
    assert set(copied) <= {'/'+c for c in QUICK_START[slug]}
    assert 'Step' in screen.rich_text
    assert all(len(row) <= 2 for row in screen.keyboard.inline_keyboard)
    assert callback(f'worker:guide:{slug}', None, theme, active=set()) is None


def test_guides_reject_unselected_and_controller_scope():
    assert callback('worker:guide:encoder', None, Theme(worker_plugins=('filestore',)), active={'encode'}) is None
    assert callback('worker:guide:encoder', None, Theme(), active={'encode'}) is None


def test_home_prioritizes_onboarding_without_repeating_every_description():
    theme = Theme(worker_plugins=('encoder', 'filestore', 'leech'))
    active = {'encode', 'get', 'leech', 'warn'}
    home = overview(None, theme, active=active)
    assert 'Get started' in str(home.keyboard)
    assert len(home.rich_text) < 2000
    assert 'Bring a public download' not in home.rich_text


def test_guides_filter_copy_buttons_and_preserve_unicode_fallback():
    theme = Theme({}, worker_plugins=('encoder',))
    screen = callback('worker:guide:encoder', None, theme, active={'compress'})
    assert screen is not None
    assert '<tg-emoji' not in screen.rich_text
    copied = [b.copy_text.text for row in screen.keyboard.inline_keyboard for b in row if b.copy_text]
    assert copied == ['/compress']
    assert all(b.icon_custom_emoji_id is None for row in screen.keyboard.inline_keyboard for b in row)
    assert callback('worker:guide:encoder:extra', None, theme, active={'compress'}) is None


def test_real_callback_dispatches_guide_and_rechecks_stale_state():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.handlers.callbacks import CallbackHandlers
    active = {'encode'}
    sender = SimpleNamespace(edit=AsyncMock(return_value=True), send=AsyncMock())
    handler = CallbackHandlers(sender, Theme(worker_plugins=('encoder',)), active_commands=lambda: active)
    async def scenario():
        query = SimpleNamespace(data='worker:guide:encoder', from_user=None, message=object(), answer=AsyncMock())
        await handler.on_callback(None, query)
        assert 'Get started' in sender.edit.await_args.args[1].rich_text
        sender.edit.reset_mock()
        active.clear()
        await handler.on_callback(None, query)
        sender.edit.assert_not_awaited()
        assert query.answer.await_args.kwargs['show_alert'] is True
    asyncio.run(scenario())


@pytest.mark.parametrize('slug,command,syntax', [
    ('encoder', 'encode', '/encode balanced'),
    ('encoder', 'compress', '/compress'),
    ('postmaker', 'post', '/post Title | body'),
    ('leech', 'leech', '/leech <public_http_url>'),
    ('ai_agent', 'ask', '/ask <question>'),
    ('renamer', 'rename', '/rename'),
    ('music', 'play', '/play'),
    ('moderation', 'settings', '/settings'),
])
def test_worker_command_details_show_reviewed_usage_and_preparation(slug, command, syntax):
    theme = Theme(worker_plugins=(slug,))
    screen = callback('worker:cmd:' + command, None, theme, active={command})
    assert screen is not None
    from agent.utils.sender import to_safe_html
    import html
    text = html.unescape(to_safe_html(screen.rich_text))
    assert syntax in text
    assert 'How to use' in text and 'Before sending' in text
    assert 'Registered here' in text and 'not a readiness check' in text
    assert 'Meiko' not in text


def test_archive_genlink_usage_is_not_confused_with_linkshare_media_reply():
    file = callback('worker:cmd:genlink', None, Theme(worker_plugins=('filestore',)), active={'genlink'})
    share = callback('worker:cmd:genlink', None, Theme(worker_plugins=('linkshare',)), active={'genlink'})
    assert 'Send the command without arguments' in file.rich_text
    assert 'Reply to a file you own' in share.rich_text
    assert 'Owner, private chat' in file.rich_text


def test_usage_guides_are_not_shown_for_unselected_or_stale_commands():
    theme = Theme(worker_plugins=('encoder',))
    assert callback('worker:cmd:ask', None, theme, active={'ask', 'encode'}) is None
    assert callback('worker:cmd:encode', None, theme, active=set()) is None
    assert callback('worker:cmd:encode', None, theme, active=None) is None
