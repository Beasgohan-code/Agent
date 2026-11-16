"""Worker identity must follow its selected plugins, not the controller UI."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.ui.screens import welcome_screen, help_screen
from agent.ui.theme import Theme


@pytest.mark.parametrize('slug,title,command', [
    ('filestore', 'FileStore', 'get'), ('encoder', 'Encoder', 'encode'),
    ('moderation', 'Group Management', 'warn'), ('postmaker', 'Post maker', 'post'),
    ('linkshare', 'Linkshare', 'genlink'), ('leech', 'Leech', 'leech'),
    ('music', 'Music', 'play'), ('ai_agent', 'AI Agent', 'ask'),
])
def test_single_plugin_worker_has_its_own_home_help_and_options(slug, title, command):
    theme = Theme(worker_plugins=(slug,))
    user = SimpleNamespace(first_name='<Alice>', last_name='')
    active = {'start', 'help', command, 'warn', 'settings'}
    for screen in (welcome_screen(user, theme, active=active), help_screen(user, theme, active=active)):
        assert title in screen.rich_text
        assert '/'+command in screen.rich_text
        assert 'Your group. Your workspace.' not in screen.rich_text
        assert 'Not registered' not in screen.rich_text
        assert '<Alice>' not in screen.rich_text
        assert screen.keyboard
        assert all(len(button.callback_data.encode()) <= 64 for row in screen.keyboard.inline_keyboard for button in row)


def test_worker_presentation_does_not_leak_between_instances():
    encoder = Theme(worker_plugins=('encoder',))
    files = Theme(worker_plugins=('filestore',))
    parent = Theme()
    active = {'start', 'help', 'get', 'encode'}
    assert 'FileStore' not in welcome_screen(None, encoder, active=active).rich_text
    assert '/encode' not in welcome_screen(None, files, active=active).rich_text
    assert 'Your group. Your workspace.' in welcome_screen(None, parent, active=active).rich_text


def test_worker_callback_rechecks_live_commands_and_rejects_forged_plugin():
    from agent.handlers.callbacks import CallbackHandlers
    theme = Theme(worker_plugins=('encoder',))
    sender = SimpleNamespace(edit=AsyncMock(return_value=True), send=AsyncMock())
    active = {'start', 'help', 'encode'}
    handler = CallbackHandlers(sender, theme, active_commands=lambda: active)

    async def scenario():
        query = SimpleNamespace(data='worker:encoder:0', from_user=None, message=SimpleNamespace(), answer=AsyncMock())
        await handler.on_callback(None, query)
        assert '/encode' in sender.edit.await_args.args[1].rich_text
        sender.edit.reset_mock()
        active.remove('encode')
        await handler.on_callback(None, query)
        sender.edit.assert_not_awaited()
        assert query.answer.await_args.kwargs.get('show_alert') is True
        query.data = 'worker:filestore:0'
        await handler.on_callback(None, query)
        sender.edit.assert_not_awaited()
    asyncio.run(scenario())


def test_multi_plugin_pagination_icons_and_unavailable_commands():
    from agent.ui.workers import plugin_screen, callback
    from agent.modules import encoder, filestore
    theme = Theme(worker_plugins=('encoder', 'filestore'))
    active = set(encoder.MANIFEST.commands) | set(filestore.MANIFEST.commands)
    screen = welcome_screen(None, theme, active=active)
    assert 'Multi-plugin' in screen.rich_text
    assert 'Encoder' in screen.rich_text and 'FileStore' in screen.rich_text
    assert 'Music' not in screen.rich_text
    for row in screen.keyboard.inline_keyboard:
        for button in row:
            if button.callback_data.startswith('worker:'):
                assert callback(button.callback_data, None, theme, active=active)
    assert plugin_screen(None, theme, 'encoder', active={'get'}) is None
    assert callback('worker:encoder:999', None, theme, active=active) is None
    assert callback('worker:encoder:-1', None, theme, active=active) is None
    assert callback('worker:unknown:0', None, theme, active=active) is None
    assert callback('worker:encoder:0', None, Theme(), active=active) is None
    theme.disable_custom_emoji()
    screen = welcome_screen(None, theme, active=active)
    assert '<tg-emoji' not in screen.rich_text
    assert all(button.icon_custom_emoji_id is None for row in screen.keyboard.inline_keyboard for button in row)
    group = Theme(worker_plugins=())
    from agent.ui.workers import commands, PAGE_SIZE
    from agent.modules import MODULES
    from agent.platform.policy import GROUP_CORE
    group_active = {command for module in MODULES if module.MANIFEST.slug in GROUP_CORE for command in module.MANIFEST.commands}
    total = len(commands('moderation', group_active))
    assert total > PAGE_SIZE
    first = plugin_screen(None, group, 'moderation', active=group_active)
    second = callback('worker:moderation:1', None, group, active=group_active)
    assert second and first.rich_text != second.rich_text
    assert 'Next' in str(first.keyboard)


def test_worker_settings_bind_identity_without_inheriting_parent_image(tmp_path):
    from dataclasses import replace
    from test_clone import build, MEMBER, TOKEN_A
    from agent.modules.clone.store import Clone
    from agent.bot import AgentBot
    ctx, _, _ = build(tmp_path)
    manager = ctx.clones
    manager._settings = replace(manager._settings, start_image='https://example.test/controller.jpg')
    clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, profile='files')
    settings = manager.settings_for(clone)
    assert settings.start_image is None
    assert settings.db_scope == 'clone:111111111' and settings.owner_id == MEMBER
    worker = AgentBot(settings)
    replacement = AgentBot(settings)
    assert worker.theme.worker_plugins == settings.plugins == replacement.theme.worker_plugins
    parent = AgentBot(replace(manager._settings, db_scope='main:123'))
    assert parent.theme.worker_plugins is None


def test_worker_deep_links_still_dispatch_before_greeting():
    from agent.handlers.commands import CommandHandlers
    sender = SimpleNamespace(send_hero=AsyncMock())
    links = SimpleNamespace(handles=lambda payload: payload.startswith('link_'), dispatch=AsyncMock())
    handler = CommandHandlers(sender, Theme(worker_plugins=('filestore',)), deeplinks=links)
    message = SimpleNamespace(text='/start link_owned', from_user=SimpleNamespace(id=7), chat=SimpleNamespace(id=7))
    asyncio.run(handler.start(None, message))
    links.dispatch.assert_awaited_once_with(None, message, 'link_owned')
    sender.send_hero.assert_not_awaited()
