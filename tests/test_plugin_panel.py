"""Agent — implementation detail."""

import asyncio
from types import SimpleNamespace

from pyrogram.enums import ButtonStyle

from agent.bot import AgentBot
from agent.config import Settings
from agent.modules import ops, select, not_selected, unknown
from agent.platform.policy import GROUP_CORE

OWNER = 11
ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
    "OWNER_ID": str(OWNER),
}


def make_bot(tmp_path, **overrides):
    settings = Settings.from_env({**ENV, "DATA_DIR": str(tmp_path / "data"), **overrides})
    bot = AgentBot(settings)
    bot.build()
    return bot


class FakeMessage:
    def __init__(self, text, *, uid=OWNER):
        self.text = text
        self.id = 7
        self.chat = SimpleNamespace(id=11)
        self.from_user = SimpleNamespace(id=uid, first_name="Owner")
        self.replies = []
        self.markup = None

    async def reply(self, text, **kwargs):
        self.replies.append(str(text))
        self.markup = kwargs.get("reply_markup")
        return SimpleNamespace(id=8)


class FakeQuery:
    def __init__(self, data, *, uid=OWNER):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.answers = []
        self.edits = []
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=11),
            id=8,
            edit_text=self._edit,
        )

    async def _edit(self, text=None, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def buttons(keyboard):
    return [b for row in keyboard.inline_keyboard for b in row]


# --- the build's plugin selection -----------------------------------------


def test_the_default_build_ships_nine_plugins_plus_the_shell(tmp_path):
    bot = make_bot(tmp_path, PLUGINS="")
    registered = {m.slug for m in bot.registry.manifests()}

    assert registered == {
        "ops",
        "core",
        "clone",
        "filestore",
        "leech",
        "linkshare",
        "moderation",
        "music",
        "postmaker",
        "encoder",
        "ai_agent",
    } | set(GROUP_CORE)
    # Optional modules left out by the deployment register nothing.
    assert {"renamer", "premium", "utilities"} <= set(not_selected(bot.settings.plugins))
    assert "encode" in set(bot.registry.active_commands())
    assert {"get", "leech", "ban", "plugins"} <= set(bot.registry.active_commands())


def test_the_shell_survives_even_when_plugins_names_nothing_else(tmp_path):
    bot = make_bot(tmp_path, PLUGINS="leech")
    registered = {m.slug for m in bot.registry.manifests()}
    commands = set(bot.registry.active_commands())

    # A build with one feature still has a front door and a way to repair it.
    assert registered == {"ops", "core", "leech"} | set(GROUP_CORE)
    assert {"menu", "about", "status", "cancel", "plugins", "plugin"} <= commands


def test_plugins_env_narrows_the_build_and_unselected_plugins_vanish(tmp_path):
    bot = make_bot(tmp_path, PLUGINS="ops,leech,filestore")
    registered = {m.slug for m in bot.registry.manifests()}

    assert registered == {"ops", "core", "leech", "filestore"} | set(GROUP_CORE)
    assert "moderation" not in not_selected(bot.settings.plugins)
    # A plugin that is not selected has no commands at all, not hidden ones.
    assert "ban" in set(bot.registry.active_commands())
    assert "leech" in set(bot.registry.active_commands())


def test_an_unknown_slug_costs_one_plugin_not_the_bot():
    assert unknown(("ops", "nope")) == ("nope",)
    assert {m.MANIFEST.slug for m in select(("ops", "nope"))} == {"ops", "core", *GROUP_CORE}


def test_star_selects_everything_compiled():
    assert len(select(("*",))) == 20


# --- the panel ------------------------------------------------------------


def test_the_panel_has_one_management_suite_and_optional_buttons(tmp_path):
    bot = make_bot(tmp_path)
    _, commands = ops.build(bot.modules)
    message = FakeMessage("/plugins")

    asyncio.run(commands["plugins"](None, message))

    assert "<pre>" in message.replies[0]          # editable classic grid
    slugs = [m.slug for m in bot.registry.manifests()]
    data = [b.callback_data for b in buttons(message.markup)]
    assert data == ["plugin:info:group"] + [f"plugin:info:{slug}" for slug in slugs if slug not in {*GROUP_CORE, "ops", "core"}]
    for button in buttons(message.markup):
        assert button.style is ButtonStyle.SUCCESS
        if button.callback_data == "plugin:info:group":
            assert button.disabled is True        # the control plane is locked


def test_browsing_plugin_is_readonly_and_disable_requires_confirmation(tmp_path):
    bot = make_bot(tmp_path)
    ops.build(bot.modules)
    query = FakeQuery('plugin:filestore')
    asyncio.run(bot.actions.dispatch(None, query))
    assert bot.registry.is_enabled('filestore')
    assert 'Plugin workspace' in str(query.edits[0][0])
    assert any(b.callback_data == 'plugin:ask:filestore' for b in buttons(query.edits[0][1]))
    ask = FakeQuery('plugin:ask:filestore')
    asyncio.run(bot.actions.dispatch(None, ask))
    assert bot.registry.is_enabled('filestore')
    assert 'every chat' in str(ask.edits[0][0])
    assert any(b.callback_data == 'plugin:off:filestore' for b in buttons(ask.edits[0][1]))
    off = FakeQuery('plugin:off:filestore')
    asyncio.run(bot.actions.dispatch(None, off))
    assert not bot.registry.is_enabled('filestore')
    assert 'filestore is off' in off.answers[0][0]
    # Explicit on is idempotent, never an inversion from stale state.
    asyncio.run(bot.actions.dispatch(None, FakeQuery('plugin:on:filestore')))
    asyncio.run(bot.actions.dispatch(None, FakeQuery('plugin:on:filestore')))
    assert bot.registry.is_enabled('filestore')


def test_the_locked_plugin_cannot_be_pressed_off(tmp_path):
    bot = make_bot(tmp_path)
    ops.build(bot.modules)
    query = FakeQuery("plugin:ops")

    asyncio.run(bot.actions.dispatch(None, query))

    assert bot.registry.is_enabled("ops") is True
    assert "locked" in query.answers[0][0]
    assert query.answers[0][1] is True            # shown as an alert


def test_a_stranger_cannot_toggle_plugins(tmp_path):
    bot = make_bot(tmp_path)
    ops.build(bot.modules)
    query = FakeQuery("plugin:moderation", uid=999)

    asyncio.run(bot.actions.dispatch(None, query))

    assert bot.registry.is_enabled("moderation") is True
    assert "owner" in query.answers[0][0].lower()


def test_the_panel_still_works_through_the_text_command(tmp_path):
    bot = make_bot(tmp_path)
    _, commands = ops.build(bot.modules)
    message = FakeMessage("/plugin filestore off")

    asyncio.run(commands["plugin"](None, message))

    assert bot.registry.is_enabled("filestore") is False
    assert "now disabled" in message.replies[0]


def test_repeated_runtime_on_does_not_emit_duplicate_plugin_events(tmp_path):
    async def scenario():
        bot = make_bot(tmp_path)
        handler = bot.registry.handler_for('plugin')
        await handler(None,FakeMessage('/plugin leech off'))
        bot.events.clear()
        await handler(None,FakeMessage('/plugin leech on'))
        assert bot.events.count('plugin') == 1
        request = FakeMessage('/plugin leech on')
        await handler(None,request)
        assert bot.events.count('plugin') == 1
        assert '/plugin leech approve' in request.replies[-1]
        assert '/plugins' in request.replies[-1]
    asyncio.run(scenario())


def test_workspace_refresh_unchanged_home_and_nonowner_controls(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from pyrogram.errors import MessageNotModified
    async def scenario():
        bot = make_bot(tmp_path)
        ops.build(bot.modules)
        editor = AsyncMock(side_effect=MessageNotModified())
        monkeypatch.setattr(ops.rich_ui, 'edit', editor)
        refresh = FakeQuery('plugin:info:filestore')
        await bot.actions.dispatch(None, refresh)
        assert refresh.answers == [(None, False)]
        home = FakeQuery('plugin:home')
        await bot.actions.dispatch(None, home)
        assert home.answers == [(None, False)]
        for control in ('info:filestore', 'off:filestore', 'on:filestore', 'ask:filestore', 'home'):
            editor.reset_mock()
            denied = FakeQuery('plugin:' + control, uid=999)
            await bot.actions.dispatch(None, denied)
            editor.assert_not_awaited()
            assert denied.answers[0][1]
        assert bot.registry.is_enabled('filestore')
    asyncio.run(scenario())


def test_persisted_off_plugins_can_be_enabled_after_rebuild_without_restart(tmp_path):
    from unittest.mock import MagicMock
    bot = make_bot(tmp_path)
    assert bot.runtime.disable('filestore')
    rebuilt = make_bot(tmp_path)
    assert not rebuilt.registry.is_enabled('filestore')
    entry = next(row for row in rebuilt.runtime.state() if row['slug'] == 'filestore')
    assert entry['tracked_handlers'] > 0
    client = MagicMock()
    rebuilt.runtime.attach(client)
    assert rebuilt.runtime.enable('filestore')
    assert rebuilt.registry.is_enabled('filestore')
    assert client.add_handler.call_count == entry['tracked_handlers']
    assert 'get' in rebuilt.registry.active_commands()
    assert not rebuilt.runtime.enable('filestore')
    assert client.add_handler.call_count == entry['tracked_handlers']


def test_already_on_and_unavailable_callbacks_explain_specific_state(tmp_path):
    bot = make_bot(tmp_path)
    ops.build(bot.modules)
    already = FakeQuery('plugin:on:filestore')
    asyncio.run(bot.actions.dispatch(None, already))
    assert 'already on' in already.answers[0][0]
    assert already.answers[0][1] is False
    missing = FakeQuery('plugin:on:ai_agent')
    asyncio.run(bot.actions.dispatch(None, missing))
    assert 'AI_API_KEY' in missing.answers[0][0]
    assert missing.answers[0][1] is True
    assert not any(b.callback_data == 'plugin:on:ai_agent' for b in buttons(missing.edits[0][1]))
