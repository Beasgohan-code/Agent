"""Client initialisation, handler wiring, error handling and delivery."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from pyrogram import Client
from pyrogram.handlers import CallbackQueryHandler, ErrorHandler, MessageHandler

from agent.bot import AgentBot
from agent.config import Settings
from agent.handlers.callbacks import CallbackHandlers
from agent.ui.keyboards import CB_HELP
from agent.ui.screens import welcome_screen
from agent.ui.theme import Theme
from agent.utils.sender import ScreenSender

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


def make_settings():
    return Settings.from_env(ENV)


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
    assert bot.handler_count == 5

    handlers = client.dispatcher.groups[0]
    assert sum(isinstance(h, MessageHandler) for h in handlers) == 3
    assert sum(isinstance(h, CallbackQueryHandler) for h in handlers) == 1
    assert sum(isinstance(h, ErrorHandler) for h in handlers) == 1


def test_duplicate_initialisation_is_prevented():
    bot = AgentBot(make_settings())
    bot.build()

    with pytest.raises(RuntimeError):
        bot.build()


def test_commands_are_private_only_and_named_correctly():
    bot = AgentBot(make_settings())
    client = bot.build()

    messages = [h for h in client.dispatcher.groups[0] if isinstance(h, MessageHandler)]
    assert len(messages) == 3
    assert all(h.filters is not None for h in messages)


def test_error_handler_logs_the_failure(caplog):
    bot = AgentBot(make_settings())
    bot.build()
    handler = MessageHandler(lambda *_: None)

    with caplog.at_level(logging.ERROR):
        asyncio.run(bot._on_error(None, ValueError("boom"), handler, None, {}, {}))

    assert "boom" in caplog.text
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
    client = FakeClient(fail_sends=1)
    sender = ScreenSender(client, Theme())

    with pytest.raises(RuntimeError):
        run_send(sender, welcome_screen(SimpleNamespace(first_name="Ada"), Theme()))


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
    assert "/start" in query.edits[0]["text"]
    assert query.edits[0]["reply_markup"] is not None


def test_unknown_callback_warns_the_user_and_does_not_edit():
    handlers, _ = make_callback_handlers()
    query = FakeQuery("menu:does-not-exist")

    asyncio.run(handlers.on_callback(None, query))

    assert query.answered[0][1] is True
    assert query.edits == []


def test_callback_falls_back_to_a_new_message_when_edit_fails():
    handlers, client = make_callback_handlers()
    query = FakeQuery(CB_HELP, edit_error=RuntimeError("message is too old"))

    asyncio.run(handlers.on_callback(None, query))

    assert [kind for kind, _ in client.calls] == ["html"]
