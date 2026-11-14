"""The Telegram command menu: scopes, validation and failure handling."""

import asyncio
import logging

import pytest
from pyrogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
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


def test_every_registered_command_is_grouped_somewhere():
    from agent.modules import MODULES

    all_names = ["start", "help", "ping"] + [
        c for module in MODULES for c in module.MANIFEST.commands
    ]
    private = names_of(menu.build_commands(all_names, group=False))
    group = names_of(menu.build_commands(all_names, group=True))

    assert sorted(private + group) == sorted(set(all_names))


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


def test_resetting_the_menu_button_uses_the_command_list():
    client = FakeClient()

    assert asyncio.run(menu.reset_menu_button(client)) is True
    assert isinstance(client.menu_buttons[0], MenuButtonCommands)


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
    bot.runtime.disable("renamer")

    assert "rename" in registered
    assert "rename" not in set(bot.registry.active_commands())


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
