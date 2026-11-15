"""Client initialisation, handler wiring, error handling and delivery."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from pyrogram import Client
from pyrogram.handlers import (
    CallbackQueryHandler,
    ChatMemberUpdatedHandler,
    ErrorHandler,
    MessageHandler,
)

from agent.bot import AgentBot
from agent.config import Settings
from agent.handlers.callbacks import CallbackHandlers
from agent.platform.actions import ActionRouter
from agent.ui.keyboards import CB_HELP
from agent.ui.screens import welcome_screen
from agent.ui.theme import Theme
from pyrogram.enums import ParseMode
from agent.utils.sender import ScreenSender

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


def make_settings(**overrides):
    # These tests count the wiring of *every* plugin, so they ask for the star
    # rather than the shipped default (eight plugins plus the shell).
    return Settings.from_env({**ENV, "PLUGINS": "*", **overrides})


class FakeMessage:
    id = 1


class FakeClient:
    """Records outgoing calls and can fail on demand."""

    def __init__(self, *, fail_sends=0):
        self.calls = []
        self.fail_sends = fail_sends
        self._send_attempts = 0

    async def send_message(self, **kwargs):
        self._send_attempts += 1
        if self._send_attempts <= self.fail_sends:
            raise RuntimeError("can't parse entities")
        self.calls.append(("html", kwargs))
        return FakeMessage()

    @property
    def html_calls(self):
        return [kwargs for kind, kwargs in self.calls if kind == "html"]


class FakeQuery:
    def __init__(self, data, user=None, *, edit_error=None):
        self.data = data
        self.from_user = user or SimpleNamespace(id=7, first_name="Ada", last_name=None)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=7))
        self.answered = []
        self.edits = []
        self.edit_error = edit_error

    async def answer(self, text=None, show_alert=False):
        self.answered.append((text, show_alert))

    async def edit_message_text(self, **kwargs):
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append(kwargs)


# --- client initialisation -------------------------------------------------


def test_build_creates_client_and_registers_handlers():
    bot = AgentBot(make_settings())

    client = bot.build()

    assert isinstance(client, Client)
    # Music registers nothing without SESSION_STRING. Count command handlers,
    # callback/error routing and isolated background watchers separately.
    assert bot.handler_count == 156

    handlers = client.dispatcher.groups[0]
    assert sum(isinstance(h, MessageHandler) for h in handlers) == 147
    assert sum(isinstance(h, CallbackQueryHandler) for h in handlers) == 1
    assert sum(isinstance(h, ErrorHandler) for h in handlers) == 1

    # Watchers must not sit in group 0, where they could shadow a command
    # handler, and each needs its own group: pyrogram runs at most one handler
    # per group per update, so sharing would let one watcher swallow another's.
    watchers = [handlers[0] for group, handlers in client.dispatcher.groups.items() if group > 0]
    for group in client.dispatcher.groups:
        if group == 0:
            continue
        assert len(client.dispatcher.groups[group]) == 1
    # Two message watchers (anti-spam, filters) and two membership watchers
    # (greetings, new-group log). Which group number each lands in follows the
    # module order, so assert the mix rather than the position.
    assert sum(isinstance(w, MessageHandler) for w in watchers) == 4
    assert sum(isinstance(w, ChatMemberUpdatedHandler) for w in watchers) == 3


def test_duplicate_initialisation_is_prevented():
    bot = AgentBot(make_settings())
    bot.build()

    with pytest.raises(RuntimeError):
        bot.build()


def test_every_command_has_a_scope_and_the_scopes_match_the_modules():
    bot = AgentBot(make_settings())
    client = bot.build()

    messages = [h for h in client.dispatcher.groups[0] if isinstance(h, MessageHandler)]
    assert len(messages) == 147
    assert all(h.filters is not None for h in messages)

    scopes = {c: m.scope for m in bot.registry.manifests() for c in m.commands}
    private = {c for c, scope in scopes.items() if scope == "private"}
    group = {c for c, scope in scopes.items() if scope == "group"}

    # Media commands stay in private chats; moderation only makes sense in groups.
    assert private == {
        "encode", "compress", "sample", "toaudio", "screens",
        "mediainfo",
        "genlink", "share", "links", "revoke",
        "clone", "mybots", "delclone", "clonestats",
    }
    assert group == {
        "warn", "warnings", "warns", "unwarn", "mute", "unmute", "kick", "ban",
        "tban", "tmute", "dban", "dmute", "dkick", "sban", "smute", "skick", "kickme", "unban", "purge", "note", "approve", "unapprove", "approval", "approved", "addblocklist", "rmblocklist", "unblocklistall", "rmblocklistall", "blocklist", "blocklistmode", "blocklistdelete", "setblocklistreason", "resetblocklistreason", "antispam", "modlog", "flood", "setflood", "setfloodtimer", "floodmode", "clearflood",
        "filter", "filters", "stopfilter",
        "setwelcome", "welcome", "goodbye",
        "settings", "rules", "setrules", "pin", "unpin",
        "promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror", "admins", "warnlimit", "resetwarns", "lockdown",
        "post", "verify",
    }


def test_error_handler_logs_the_failure(caplog):
    bot = AgentBot(make_settings())
    bot.build()
    handler = MessageHandler(lambda *_: None)

    with caplog.at_level(logging.ERROR):
        asyncio.run(bot._on_error(None, ValueError("boom"), handler, None, {}, {}))

    assert "boom" not in caplog.text
    assert "incident=" in caplog.text
    assert "ValueError" in caplog.text


# --- delivery --------------------------------------------------------------


def run_send(sender, screen, chat_id=7):
    return asyncio.run(sender.send(chat_id, screen))


def test_sender_uses_html_by_default():
    client = FakeClient()
    sender = ScreenSender(client, Theme())

    message = run_send(sender, welcome_screen(SimpleNamespace(first_name="Ada"), Theme()))

    assert isinstance(message, FakeMessage)
    assert [kind for kind, _ in client.calls] == ["html"]
    assert "<h2>" not in client.html_calls[0]["text"]


def test_sender_retries_without_custom_emoji_when_rejected():
    theme = Theme({"wave": 5368324170671202286})
    client = FakeClient(fail_sends=1)
    sender = ScreenSender(client, theme)

    run_send(sender, welcome_screen(SimpleNamespace(first_name="Ada"), theme))

    assert len(client.html_calls) == 1
    assert "<tg-emoji" not in client.html_calls[0]["text"]
    assert theme.custom_emoji_enabled is False


def test_sender_reraises_when_nothing_can_be_retried():
    # No custom emoji in this theme, so there is nothing to retry without and
    # the transport error must surface instead of being swallowed.
    theme = Theme({})
    client = FakeClient(fail_sends=1)
    sender = ScreenSender(client, theme)

    with pytest.raises(RuntimeError):
        run_send(sender, welcome_screen(SimpleNamespace(first_name="Ada"), theme))


def test_sender_keeps_custom_emoji_when_accepted():
    theme = Theme({"wave": 5368324170671202286})
    client = FakeClient()
    sender = ScreenSender(client, theme)

    run_send(sender, welcome_screen(SimpleNamespace(first_name="Ada"), theme))

    assert "<tg-emoji" in client.html_calls[0]["text"]
    assert theme.custom_emoji_enabled is True


# --- callback handling -----------------------------------------------------


def make_callback_handlers():
    client = FakeClient()
    theme = Theme()
    return CallbackHandlers(ScreenSender(client, theme), theme), client


def test_known_callback_answers_and_edits_the_message():
    handlers, _ = make_callback_handlers()
    query = FakeQuery(CB_HELP)

    asyncio.run(handlers.on_callback(None, query))

    assert query.answered == [(None, False)]
    assert len(query.edits) == 1
    assert "Help" in query.edits[0]["text"]
    assert query.edits[0]["reply_markup"] is not None


def test_unknown_callback_warns_the_user_and_does_not_edit():
    handlers, _ = make_callback_handlers()
    query = FakeQuery("menu:does-not-exist")

    asyncio.run(handlers.on_callback(None, query))

    assert query.answered[0][1] is True
    assert query.edits == []


def test_callback_replaces_only_explicitly_uneditable_messages():
    handlers, client = make_callback_handlers()
    query = FakeQuery(CB_HELP, edit_error=RuntimeError("MESSAGE_EDIT_TIME_EXPIRED"))

    asyncio.run(handlers.on_callback(None, query))

    assert [kind for kind, _ in client.calls] == ["html"]


def test_a_module_callback_is_routed_before_the_menu_screens():
    """A press owned by a module never falls through to "unknown button"."""
    theme = Theme()
    client = FakeClient()
    router = ActionRouter()
    seen = []

    async def owned(_client, query, rest):
        seen.append(rest)
        await query.answer("owned")

    router.register("verify", owned)
    handlers = CallbackHandlers(
        ScreenSender(client, theme), theme, router=router
    )
    query = FakeQuery("verify:-100:5")

    asyncio.run(handlers.on_callback(None, query))

    assert seen == ["-100:5"]
    assert query.answered == [("owned", False)]
    assert query.edits == []


def test_voice_stays_off_without_a_session_string():
    bot = AgentBot(make_settings())
    bot.build()

    assert bot.voice is None
    assert "music" in {m.slug for m in bot.registry.manifests()}
    music = next(m for m in bot.registry.manifests() if m.slug == "music")
    # No engine here, so the module must claim no commands at all.
    assert music.commands == ()


# --- the wiring bug that made /plugins answer "runtime is unavailable" ------


class OwnerMessage:
    """A message from the configured owner, with a real reply method."""

    def __init__(self, text):
        self.text = text
        self.chat = SimpleNamespace(id=7)
        self.from_user = SimpleNamespace(id=11, first_name="Owner")
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


def owner_bot(tmp_path):
    settings = Settings.from_env(
        {**ENV, "OWNER_ID": "11", "DATA_DIR": str(tmp_path)}
    )
    bot = AgentBot(settings)
    bot.build()
    return bot


def test_the_client_parses_html_so_replies_are_not_shown_as_raw_tags():
    bot = AgentBot(make_settings())

    client = bot.build()

    assert client.parse_mode is ParseMode.HTML


def test_modules_see_the_shared_services_while_they_build(tmp_path):
    """Attaching the services after the modules built left them holding None."""
    bot = owner_bot(tmp_path)

    assert bot.modules.runtime is bot.runtime
    assert bot.modules.events is bot.events
    assert bot.modules.lease is bot.lease
    assert bot.modules.logbook is bot.logbook
    assert bot.modules.registry is bot.registry
    assert bot.modules.client is bot.client


def test_the_plugins_command_answers_instead_of_reporting_no_runtime(tmp_path):
    bot = owner_bot(tmp_path)
    handler = bot.registry.handler_for("plugins")
    message = OwnerMessage("/plugins")

    asyncio.run(handler(None, message))

    body = message.replies[0]
    assert "Plugin runtime" in body
    assert "unavailable" not in body
    assert "Encoder" in body


def test_the_events_command_sees_the_real_event_log(tmp_path):
    bot = owner_bot(tmp_path)
    bot.events.emit("command", name="start")
    handler = bot.registry.handler_for("events")
    message = OwnerMessage("/events")

    asyncio.run(handler(None, message))

    assert "No event log in this runtime" not in message.replies[0]
    assert "command" in message.replies[0]


def test_the_watchdog_command_sees_the_lease(tmp_path):
    bot = owner_bot(tmp_path)
    handler = bot.registry.handler_for("watchdog")
    message = OwnerMessage("/watchdog")

    asyncio.run(handler(None, message))

    # The lease is wired, so the panel either reports it or says it is not held;
    # it must not silently drop the row.
    assert "Instance" in message.replies[0]
