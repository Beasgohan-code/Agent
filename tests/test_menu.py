"""The Telegram command menu: scopes, validation and failure handling."""

import asyncio
import logging

import pytest
from pyrogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
    MenuButtonDefault,
)

from agent.bot import AgentBot
from agent.config import Settings
from agent.platform import menu

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


def settings_in(tmp_path):
    """Settings pointing at a throwaway data dir, never the repo's own."""
    return Settings.from_env({**ENV, "DATA_DIR": str(tmp_path)})


class FakeClient:
    def __init__(self, *, fail_commands=False, fail_button=False):
        self.commands = []
        self.menu_buttons = []
        self._fail_commands = fail_commands
        self._fail_button = fail_button

    async def set_bot_commands(self, commands, scope=None):
        if self._fail_commands:
            raise RuntimeError("not enough rights")
        self.commands.append((scope, commands))
        return True

    async def set_chat_menu_button(self, chat_id=None, menu_button=None):
        if self._fail_button:
            raise RuntimeError("bad request")
        self.menu_buttons.append(menu_button)
        return True


class _Capture(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink.append(record.getMessage())


def _collect_logs() -> list[str]:
    """Our logger does not propagate to root, so attach a handler directly."""
    sink: list[str] = []
    logger = logging.getLogger("agent.platform.menu")
    handler = _Capture(sink)
    logger.addHandler(handler)
    pytest.logs_attached = handler  # keep a reference for teardown below
    _ATTACHED.append((logger, handler))
    return sink


_ATTACHED: list[tuple[logging.Logger, logging.Handler]] = []


@pytest.fixture(autouse=True)
def _detach_capture():
    yield
    while _ATTACHED:
        logger, handler = _ATTACHED.pop()
        logger.removeHandler(handler)


def names_of(batch):
    return [c.command for c in batch]


# --- scopes ----------------------------------------------------------------


def test_group_commands_do_not_leak_into_private_chats():
    private = menu.build_commands(["start", "ban", "ping", "filter"], group=False)
    group = menu.build_commands(["start", "ban", "ping", "filter"], group=True)

    assert names_of(private) == ["start", "ping"]
    assert names_of(group) == ["ban", "filter"]


def test_registered_commands_are_grouped_up_to_telegram_scope_limit():
    from agent.modules import MODULES

    all_names = ["start", "help", "ping"] + [
        c for module in MODULES for c in module.MANIFEST.commands
    ]
    private = names_of(menu.build_commands(all_names, group=False))
    group = names_of(menu.build_commands(all_names, group=True))

    # Telegram caps each scope at 100 entries; /help retains all handlers.
    unique = list(dict.fromkeys(all_names))
    expected_private = [name for name in unique if name not in menu.GROUP_ONLY]
    expected_group = [name for name in unique if name in menu.GROUP_ONLY]
    assert len(private) == min(len(expected_private), menu.MAX_COMMANDS)
    assert len(group) == min(len(expected_group), menu.MAX_COMMANDS)
    assert set(private) <= set(expected_private)
    assert set(group) <= set(expected_group)
    assert {'settings', 'voicehealth'} <= set(group)
    assert {'help', 'plugins', 'clone'} <= set(private)
    from agent.ui.screens import HELP_SECTIONS
    help_names = {name for _, _, commands in HELP_SECTIONS for name in commands}
    assert set(unique) <= help_names | {"start", "help", "ping"}


def test_names_are_validated_and_deduplicated():
    commands = menu.build_commands(["Start", "/help", "bad-name", "ok_name", "start"])

    assert names_of(commands) == ["start", "help", "ok_name"]


def test_every_command_has_a_real_description():
    from agent.modules import MODULES

    all_names = ["start", "help", "ping"] + [
        c for module in MODULES for c in module.MANIFEST.commands
    ]

    missing = [name for name in all_names if name not in menu.DESCRIPTIONS]

    assert missing == []


def test_descriptions_stay_within_telegram_limits():
    for command in menu.build_commands(list(menu.DESCRIPTIONS)):
        assert 1 <= len(command.command) <= 32
        assert len(command.description) <= menu.MAX_DESCRIPTION


def test_the_list_is_capped():
    names = [f"cmd_{index}" for index in range(150)]

    assert len(menu.build_commands(names, group=False)) == menu.MAX_COMMANDS


# --- publishing ------------------------------------------------------------


def test_publishing_sets_both_scopes():
    client = FakeClient()

    private_count, group_count = asyncio.run(
        menu.publish(client, ["start", "ban", "ping", "warn"])
    )

    scopes = [type(scope) for scope, _commands in client.commands]
    assert BotCommandScopeDefault in scopes
    assert BotCommandScopeAllGroupChats in scopes
    assert (private_count, group_count) == (2, 2)


def test_a_failed_publish_is_logged_not_raised():
    client = FakeClient(fail_commands=True)
    messages = _collect_logs()

    result = asyncio.run(menu.publish(client, ["start", "ban"]))

    assert result == (0, 0)
    assert any("Could not publish the command menu" in m for m in messages)


def test_resetting_the_menu_button_uses_telegram_default():
    client = FakeClient()

    assert asyncio.run(menu.reset_menu_button(client)) is True
    assert isinstance(client.menu_buttons[0], MenuButtonDefault)


def test_a_failed_menu_button_reset_is_reported_not_raised():
    client = FakeClient(fail_button=True)
    messages = _collect_logs()

    assert asyncio.run(menu.reset_menu_button(client)) is False
    assert any("Could not reset" in m for m in messages)


# --- configuration ---------------------------------------------------------


def test_sync_commands_is_on_by_default_and_can_be_disabled():
    assert Settings.from_env(ENV).sync_commands is True
    assert Settings.from_env({**ENV, "SYNC_COMMANDS": "0"}).sync_commands is False


def test_the_published_names_come_from_the_registry_not_a_stale_list(tmp_path):
    bot = AgentBot(settings_in(tmp_path))
    bot.build()
    registered = set(bot.registry.active_commands())

    # A disabled plugin disappears from the menu as well as from the dispatcher.
    bot.runtime.disable("encoder")

    assert "encode" in registered
    assert "encode" not in set(bot.registry.active_commands())


def test_the_menu_scope_matches_each_module_declared_scope():
    """A group module must not publish its commands into the default scope."""
    from agent.modules import MODULES
    from agent.platform.menu import GROUP_ONLY

    for module in MODULES:
        scope = module.MANIFEST.scope
        for command in module.MANIFEST.commands:
            if scope == "group":
                assert command in GROUP_ONLY, f"{command} runs only in groups but is not group-scoped"
            elif scope == "private":
                assert command not in GROUP_ONLY, f"{command} runs only in private but is group-scoped"


def test_manifest_scopes_include_common_commands_in_groups_not_private_controls():
    async def scenario():
        client = FakeClient()
        names = ['start', 'uptime', 'clone', 'ban']
        counts = await menu.publish(client, names, command_scopes={
            'start': 'all', 'uptime': 'all', 'clone': 'private', 'ban': 'group'})
        assert counts == (3, 3)
        lists = {type(scope): {item.command for item in commands} for scope, commands in client.commands}
        assert lists[BotCommandScopeAllGroupChats] == {'start', 'uptime', 'ban'}
        assert lists[BotCommandScopeDefault] == {'start', 'uptime', 'clone'}
    asyncio.run(scenario())


def test_empty_command_scope_is_published_to_clear_old_commands():
    client = FakeClient()
    assert asyncio.run(menu.publish(client, [])) == (0, 0)
    assert len(client.commands) == 2
    assert all(not commands for _, commands in client.commands)


def test_connected_runtime_toggle_refreshes_commands_without_unavailable_plugins(tmp_path):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    async def scenario():
        bot = AgentBot(settings_in(tmp_path))
        bot.build()
        client = SimpleNamespace(is_connected=True, set_bot_commands=AsyncMock(),
                                 set_chat_menu_button=AsyncMock())
        bot._client = client
        await bot._sync_commands(client, reset_button=True)
        assert isinstance(client.set_chat_menu_button.await_args.kwargs['menu_button'], MenuButtonDefault)
        client.set_bot_commands.reset_mock()
        bot.runtime.disable('encoder')
        await bot._menu_sync_task
        published = {item.command for call in client.set_bot_commands.await_args_list for item in call.args[0]}
        assert 'encode' not in published
        assert 'play' not in published  # no configured assistant/voice engine
        assert 'uptime' in published
        client.set_bot_commands.reset_mock()
        bot.runtime.enable('encoder')
        await bot._menu_sync_task
        published = {item.command for call in client.set_bot_commands.await_args_list for item in call.args[0]}
        assert 'encode' in published
    asyncio.run(scenario())


def test_disabling_command_sync_does_not_force_commands_menu_button(tmp_path):
    from dataclasses import replace
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    async def scenario():
        bot = AgentBot(replace(settings_in(tmp_path), sync_commands=False))
        client = SimpleNamespace(set_bot_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
        await bot._sync_commands(client, reset_button=True)
        client.set_bot_commands.assert_not_awaited()
        assert isinstance(client.set_chat_menu_button.await_args.kwargs['menu_button'], MenuButtonDefault)
    asyncio.run(scenario())


def test_telegram_registration_and_button_reset_are_timeout_bounded(monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    async def scenario():
        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()
        monkeypatch.setattr(menu, 'SYNC_TIMEOUT', 0.001)
        client = SimpleNamespace(set_bot_commands=AsyncMock(side_effect=blocked),
                                 set_chat_menu_button=AsyncMock(side_effect=blocked))
        assert await menu.publish(client, ['start', 'ban']) == (0, 0)
        assert await menu.reset_menu_button(client) is False
    asyncio.run(scenario())


def test_mid_sync_toggle_is_not_lost(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    async def scenario():
        bot = AgentBot(settings_in(tmp_path))
        bot.build()
        entered, proceed = asyncio.Event(), asyncio.Event()
        calls = []
        async def publish(commands, **kwargs):
            calls.append({item.command for item in commands})
            if len(calls) == 1:
                entered.set()
                await proceed.wait()
        client = SimpleNamespace(is_connected=True, set_bot_commands=AsyncMock(side_effect=publish))
        bot._client = client
        bot.runtime.disable('encoder')
        await entered.wait()
        bot.runtime.enable('encoder')
        proceed.set()
        await bot._menu_sync_task
        assert len(calls) == 4  # two scopes, followed by the latest state
        assert 'encode' in calls[-2]
    asyncio.run(scenario())


def test_overflow_menu_keeps_cross_feature_entry_points():
    names = [f'command_{index}' for index in range(120)] + ['settings', 'plugins', 'menu', 'voicehealth', 'reports']
    commands = menu.build_commands(names)
    assert len(commands) <= 100
    assert {'plugins', 'menu'} <= set(names_of(commands))
    assert len(names_of(commands)) == len(set(names_of(commands)))


def test_actual_builtin_menu_scopes_match_group_navigation_and_home_catalogue(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    async def scenario():
        bot = AgentBot(settings_in(tmp_path))
        bot.build()
        assert set(bot._visible_commands()) == set(bot.registry.active_commands()) | {'start', 'help', 'ping'}
        client = SimpleNamespace(set_bot_commands=AsyncMock())
        await bot._sync_commands(client)
        lists = {type(call.kwargs['scope']): {item.command for item in call.args[0]}
                 for call in client.set_bot_commands.await_args_list}
        from pyrogram.types import BotCommandScopeDefault, BotCommandScopeAllGroupChats
        assert {'start', 'help', 'ping'} <= lists[BotCommandScopeDefault]
        assert {'start','help'} <= lists[BotCommandScopeAllGroupChats]
        assert 'ping' not in lists[BotCommandScopeAllGroupChats]
    asyncio.run(scenario())
