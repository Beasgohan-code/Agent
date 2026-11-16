"""Worker specialization is a registration boundary, not a hidden menu."""
from dataclasses import replace

import pytest

from agent.bot import AgentBot
from agent.config import Settings
from agent.modules import MODULES
from agent.platform.policy import GROUP_CORE
from test_bot import ENV


def build_worker(tmp_path, plugins):
    settings = replace(Settings.from_env(ENV), data_dir=tmp_path, db_scope='clone:123456789',
                       plugins=plugins, owner_id=7, start_image=None)
    bot = AgentBot(settings)
    bot.build()  # Actual Wzgram handler registration; no Telegram connection.
    return bot


@pytest.mark.parametrize('plugins', [('moderation',), (), tuple(GROUP_CORE)])
def test_group_worker_registers_group_commands_and_navigation_only(tmp_path, plugins):
    bot = build_worker(tmp_path, plugins)
    group_commands = {command for module in MODULES if module.MANIFEST.slug in GROUP_CORE for command in module.MANIFEST.commands}
    registered = set(bot.registry.active_commands())
    assert registered == group_commands | {'menu', 'about'}
    assert {m.slug for m in bot.registry.manifests()} == set(GROUP_CORE) | {'core'}
    assert not bot.actions.handles('plugin:home')
    for forbidden in ('restart', 'db', 'clone', 'premium', 'addpremium', 'play', 'ask', 'encode', 'jobs', 'cancel', 'owner'):
        assert bot.registry.handler_for(forbidden) is None
        assert forbidden not in bot._visible_commands()
    assert bot.plugin_gate is not None  # Mandatory protection remains gated by its own permissions.


@pytest.mark.parametrize('slug,command', [('encoder', 'encode'), ('leech', 'leech'), ('filestore', 'get')])
def test_optional_worker_keeps_selected_tools_and_required_plugin_controls(tmp_path, slug, command):
    bot = build_worker(tmp_path, (slug,))
    registered = set(bot.registry.active_commands())
    assert command in registered
    assert {'plugins', 'plugin', 'menu', 'about'} <= registered
    assert not {'restart', 'db', 'owner', 'addsudo', 'clone', 'plans', 'addpremium'} & registered
    assert {m.slug for m in bot.registry.manifests()} == set(GROUP_CORE) | {'core', 'ops', slug}
    if slug == 'filestore':
        assert not {'jobs', 'cancel', 'encode', 'leech', 'ask'} & registered
    else:
        assert {'jobs', 'cancel'} <= registered
    assert bot.actions.handles('plugin:home')


def test_legacy_worker_selection_cannot_import_controller_commands(tmp_path):
    bot = build_worker(tmp_path, ('moderation', 'clone', 'ops', 'premium'))
    assert set(bot.registry.active_commands()) == {
        command for module in MODULES if module.MANIFEST.slug in GROUP_CORE for command in module.MANIFEST.commands
    } | {'menu', 'about'}
    assert not bot.actions.handles('clone:home')
    assert not bot.actions.handles('plugin:home')


def test_worker_rejects_forged_controller_help_callbacks(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.handlers.callbacks import CallbackHandlers
    bot = build_worker(tmp_path, ('moderation',))
    sender = SimpleNamespace(edit=AsyncMock(), send=AsyncMock())
    callbacks = CallbackHandlers(sender, bot.theme, router=bot.actions,
                                 active_commands=bot.registry.active_commands)
    async def scenario():
        for data in ('help:encoder', 'help:premium', 'plugin:home', 'clone:home'):
            query = SimpleNamespace(data=data, from_user=None, message=SimpleNamespace(), answer=AsyncMock())
            await callbacks.on_callback(None, query)
            sender.edit.assert_not_awaited()
            assert query.answer.await_args.kwargs.get('show_alert') is True
    asyncio.run(scenario())
