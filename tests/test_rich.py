"""Rich delivery: native tables when Telegram takes them, the grid when it does not."""

import asyncio
from types import SimpleNamespace

import pytest

from agent.platform.credits import CREDITS, NOTICE
from agent.ui import tables
from agent.ui.tables import Table, kv_table, panel
from agent.utils import rich


class FakeClient:
    """A client that either supports rich messages or does not."""

    def __init__(self, *, rich=True, fail_rich=False):
        self.calls = []
        self.fail_rich = fail_rich
        if rich:
            self.send_rich_message = self._send_rich
        self.send_message = self._send_message

    async def _send_rich(self, **kwargs):
        if self.fail_rich:
            raise RuntimeError("RICH_MESSAGE_UNSUPPORTED")
        self.calls.append(("rich", kwargs))
        return SimpleNamespace(id=1)

    async def _send_message(self, **kwargs):
        self.calls.append(("plain", kwargs))
        return SimpleNamespace(id=2)


class FakeMessage:
    def __init__(self, client, text=""):
        self._client = client
        self.chat = SimpleNamespace(id=-100)
        self.id = 42
        self.text = text
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append((str(text), kwargs))
        return SimpleNamespace(id=3)


@pytest.fixture()
def restore_rich():
    yield
    tables.set_rich(True)


def test_only_rich_tags_ask_for_a_rich_message():
    assert rich.needs_rich("<h2>title</h2>")
    assert rich.needs_rich('<table border="1"><tr><td>a</td></tr></table>')
    assert not rich.needs_rich("<b>bold</b>")
    assert not rich.needs_rich("<pre>grid</pre>")
    assert not rich.needs_rich("")


def test_a_rich_client_gets_a_native_table():
    client = FakeClient()
    message = FakeMessage(client)

    asyncio.run(rich.reply(message, panel("X", table=kv_table([("a", "1")]))))

    kinds = [kind for kind, _ in client.calls]
    assert kinds == ["rich"]
    html = client.calls[0][1]["rich_text"].html
    assert "<table" in html
    assert message.replies == []


def test_a_client_without_rich_support_gets_classic_html(restore_rich):
    client = FakeClient(rich=False)
    message = FakeMessage(client)

    asyncio.run(rich.reply(message, panel("X", table=kv_table([("a", "1")]))))

    sent, _kwargs = message.replies[0]
    assert client.calls == []
    assert "<table" not in sent
    assert "a" in sent and "1" in sent
    # A client that cannot send rich messages at all: no point drawing tables.
    assert tables.rich_enabled() is False


def test_a_refusal_downgrades_the_ui_and_still_delivers(restore_rich):
    client = FakeClient(fail_rich=True)
    message = FakeMessage(client)
    body = panel("X", table=kv_table([("a", "1")]))

    asyncio.run(rich.reply(message, body))

    assert tables.rich_enabled() is False
    sent, _kwargs = message.replies[0]
    assert "<table" not in sent
    assert "a" in sent and "1" in sent


def test_plain_strings_stay_ordinary_replies():
    client = FakeClient()
    message = FakeMessage(client)

    asyncio.run(rich.reply(message, "Usage: <code>/play</code>"))

    assert client.calls == []
    assert message.replies[0][0] == "Usage: <code>/play</code>"


def test_send_uses_the_same_two_paths(restore_rich):
    client = FakeClient()
    asyncio.run(rich.send(client, -100, panel("X", table=Table(rows=(("a",),)))))
    assert [kind for kind, _ in client.calls] == ["rich"]

    plain_client = FakeClient(rich=False)
    asyncio.run(rich.send(plain_client, -100, panel("X", table=Table(rows=(("a",),)))))
    assert [kind for kind, _ in plain_client.calls] == ["plain"]


def test_available_is_a_capability_check_not_a_promise():
    assert rich.available(FakeClient()) is True
    assert rich.available(object()) is False


# --- credits ---------------------------------------------------------------


def test_every_credit_is_in_the_doc():
    doc = open("docs/CREDITS.md", encoding="utf-8").read()
    for credit in CREDITS:
        assert credit.name in doc
        assert credit.url in doc
        assert credit.licence in doc
    assert NOTICE in doc


def test_every_credit_states_a_licence():
    assert {c.licence for c in CREDITS} <= {
        "no licence file",
        "MIT",
        "AGPL-3.0",
        "LGPL-3.0",
        "Attribution & personal use",
    }
