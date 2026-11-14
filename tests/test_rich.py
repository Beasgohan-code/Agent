"""Rich delivery: native tables when Telegram takes them, the grid when it does not."""

import asyncio
from types import SimpleNamespace

import pytest

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


class FakeQuery:
    """A callback query whose client may or may not speak rich messages."""

    def __init__(self, client, *, edit_error=None):
        self._client = client
        self.message = SimpleNamespace(chat=SimpleNamespace(id=-100), id=9)
        self.edits = []
        self.edit_error = edit_error

    async def edit_message_text(self, **kwargs):
        # A refusal is about the rich attempt only; the grid still goes through.
        if self.edit_error is not None and "rich_text" in kwargs:
            raise self.edit_error
        self.edits.append(kwargs)
        return SimpleNamespace(id=9)


def test_a_rich_client_edits_in_place_and_keeps_the_table():
    """Navigating a table screen must not collapse it into a grid."""
    client = FakeClient()
    query = FakeQuery(client)

    asyncio.run(rich.edit(query, panel("X", table=kv_table([("a", "1")]))))

    assert len(query.edits) == 1
    rich_edit = query.edits[0]
    assert "rich_text" in rich_edit
    assert "<table" in rich_edit["rich_text"].html
    assert "text" not in rich_edit


def test_a_plain_client_gets_the_grid_on_edit(restore_rich):
    client = FakeClient(rich=False)
    query = FakeQuery(client)

    asyncio.run(rich.edit(query, panel("X", table=kv_table([("a", "1")]))))

    edit = query.edits[0]
    assert "rich_text" not in edit
    assert "<table" not in edit["text"]
    assert "<pre>" in edit["text"]          # drawn, not flattened
    assert edit["parse_mode"] == "html"


def test_a_refused_rich_edit_falls_back_to_the_grid(restore_rich):
    client = FakeClient()
    query = FakeQuery(client, edit_error=RuntimeError("RICH_TEXT_INVALID"))

    asyncio.run(rich.edit(query, panel("X", table=kv_table([("a", "1")]))))

    assert len(query.edits) == 1
    assert "<pre>" in query.edits[0]["text"]


def test_a_native_table_survives_the_classic_form_as_a_grid():
    body = Table(
        headers=("Command", "What it does"),
        rows=(("/pin", "Pin the replied message"), ("/rules", "Show this group's rules")),
    ).rich_block()

    classic = rich.classic(body)

    assert "<table" not in classic
    assert "<pre>" in classic
    assert "\u250c" in classic               # the box survives, aligned
    assert "/pin" in classic and "Pin the replied message" in classic


def test_the_menu_and_help_are_delivered_as_rich_messages():
    """The screens a user opens first arrive as tables, not as a grid."""
    from types import SimpleNamespace as NS

    from agent.ui.screens import help_screen, welcome_screen
    from agent.ui.theme import Theme
    from agent.utils.sender import ScreenSender

    client = FakeClient()
    sender = ScreenSender(client, Theme())
    user = NS(id=7, first_name="Ada", last_name=None, language_code="en")

    asyncio.run(sender.send(-100, help_screen(user, Theme(), active={"start", "help"})))
    asyncio.run(sender.send(-100, welcome_screen(user, Theme())))

    rich_payloads = [kwargs["rich_text"].html for kind, kwargs in client.calls if kind == "rich"]
    assert len(rich_payloads) == 2
    assert "<table" in rich_payloads[0] and "<h2>Help</h2>" in rich_payloads[0]
    assert "/about" not in rich_payloads[0]      # no bibliography anywhere
    assert "<table" in rich_payloads[1]


def test_navigating_help_edits_the_rich_message_in_place():
    from types import SimpleNamespace as NS

    from agent.ui.screens import _section_builder
    from agent.ui.theme import Theme
    from agent.utils.sender import ScreenSender

    client = FakeClient()
    query = FakeQuery(client)
    user = NS(id=7, first_name="Ada", last_name=None, language_code="en")

    ok = asyncio.run(
        ScreenSender(client, Theme()).edit(
            query, _section_builder("Essentials")(user, Theme(), active={"start", "help"})
        )
    )

    assert ok is True
    assert len(query.edits) == 1
    html = query.edits[0]["rich_text"].html
    assert "<table" in html
    assert "/start" in html


def test_a_query_without_an_editor_is_left_alone():
    assert asyncio.run(rich.edit(SimpleNamespace(), "<h2>x</h2>")) is None


def test_available_is_a_capability_check_not_a_promise():
    assert rich.available(FakeClient()) is True
    assert rich.available(object()) is False


# --- the packages themselves ----------------------------------------------


def test_every_ported_plugin_is_a_package_not_a_single_file():
    """A plugin is a folder: manifest in __init__, helpers beside it."""
    import pathlib

    root = pathlib.Path("agent/modules")
    for name in ("filestore", "leech", "music", "reports", "postmaker", "security", "premium"):
        package = root / name
        assert package.is_dir(), f"{name} should be a package"
        assert (package / "__init__.py").is_file()
        siblings = [p for p in package.glob("*.py") if p.name != "__init__.py"]
        assert siblings, f"{name} should keep its helpers in sibling modules"
