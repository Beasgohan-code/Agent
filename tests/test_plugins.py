"""The Meikoagent-derived plugins: leech safety, vault, reports, posts, verify.

Everything here runs offline. The parts that need Telegram (restrict, send) are
faked; the parts that decide things — URL validation, numbering, escaping,
queue order — are the real code.
"""

import asyncio
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

from agent.config import Settings
from agent.modules import filestore, postmaker, reports, security
from agent.modules.music import build as build_music
from agent.modules.music import clock
from agent.modules.music.queue import ChatQueue, QueueBook, Track
from agent.platform.actions import ActionRouter
from agent.platform.chats import ChatStore
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.net import LinkError, address_is_public, human_bytes, parse_url
from agent.platform.storage import Storage
from agent.platform.voice import Playback, capability
from agent.ui.theme import Theme

CHAT = -1001234567890
OWNER = 11

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
    "OWNER_ID": str(OWNER),
}


def make_ctx(tmp_path):
    settings = Settings.from_env(ENV)
    return ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "test-secret"),
        chats=ChatStore(tmp_path / "chats"),
    )


class FakeMessage:
    def __init__(self, text="", *, uid=11, reply_to=None, chat_type=ChatType.SUPERGROUP):
        self.text = text
        self.reply_to_message = reply_to
        self.id = 500
        self.from_user = SimpleNamespace(id=uid, first_name="Tester", is_bot=False)
        self.chat = SimpleNamespace(id=CHAT, type=chat_type)
        self.replies: list[str] = []

    async def reply(self, text, **_kwargs):
        self.replies.append(text)


class FakeQuery:
    """A callback press: the data, who pressed it, and what it answered."""

    def __init__(self, data, uid):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.answers: list[str] = []

    async def answer(self, text="", show_alert=False):
        self.answers.append(text)


class FakeClient:
    def __init__(self):
        self.calls = []

    async def restrict_chat_member(self, chat_id, user_id, permissions, **kwargs):
        self.calls.append(("restrict", int(user_id)))

    async def ban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("ban", int(user_id)))

    async def unban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("unban", int(user_id)))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("send", text))
        return SimpleNamespace(id=777)

    async def edit_message_text(self, chat_id, message_id, text):
        self.calls.append(("edit", int(message_id), text))

    async def send_document(self, chat_id, path, **kwargs):
        self.calls.append(("document", str(path)))


def run(handler, message, client=None):
    asyncio.run(handler(client or FakeClient(), message))


# --- outbound URL safety ---------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/x", "http://user:pw@example.com/x", "http://localhost/x", "nonsense"],
)
def test_links_that_must_be_refused(url):
    with pytest.raises(LinkError):
        parse_url(url)


def test_public_url_passes_validation():
    assert parse_url("https://example.com/a.mp3") == "https://example.com/a.mp3"


def test_loopback_resolution_is_refused():
    ok, reason = address_is_public("127.0.0.1")
    assert ok is False
    assert "private" in reason


def test_human_bytes_rounds_to_one_decimal():
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(512) == "512 B"


# --- module-owned callbacks ------------------------------------------------


def test_action_router_refuses_two_owners_for_one_prefix():
    router = ActionRouter()
    router.register("verify", lambda *_: None)
    with pytest.raises(ValueError):
        router.register("verify", lambda *_: None)
    assert router.handles("verify:-100:5")
    assert not router.handles("menu:main")


def test_action_router_passes_the_rest_of_the_data():
    seen = {}

    async def handler(client, query, rest):
        seen["rest"] = rest

    router = ActionRouter()
    router.register("verify", handler)
    query = SimpleNamespace(data="verify:-100:5")
    assert asyncio.run(router.dispatch(None, query)) is True
    assert seen["rest"] == "-100:5"


def test_action_router_reports_an_unknown_prefix():
    router = ActionRouter()
    assert asyncio.run(router.dispatch(None, SimpleNamespace(data="menu:main"))) is False


# --- voice engine availability --------------------------------------------

def test_voice_needs_a_session_string():
    ok, reason = capability(None)
    assert ok is False
    assert "SESSION_STRING" in reason


def test_playback_elapsed_freezes_while_paused():
    playback = Playback("x", "https://example.com/a.mp3", started_at=100.0, paused_at=110.0)
    assert playback.elapsed == pytest.approx(10.0)
    assert playback.paused is True


def test_music_registers_nothing_without_an_engine(tmp_path):
    ctx = make_ctx(tmp_path)
    manifest, commands = build_music(ctx)
    assert commands == {}
    assert manifest.commands == ()
    assert "unavailable" in manifest.description


def test_music_clock():
    assert clock(0) == "0:00"
    assert clock(65) == "1:05"
    assert clock(3725) == "1:02:05"


# --- queue ----------------------------------------------------------------


def test_queue_plays_in_order_then_empties():
    queue = ChatQueue()
    queue.add(Track("one", "u1"))
    queue.add(Track("two", "u2"))
    assert queue.advance().title == "one"
    assert queue.advance().title == "two"
    assert queue.advance() is None
    assert queue.size == 0


def test_queue_loop_repeats_the_current_track():
    queue = ChatQueue()
    queue.add(Track("one", "u1"))
    queue.advance()
    queue.loop = True
    assert queue.advance().title == "one"


def test_queue_remove_and_book():
    book = QueueBook()
    queue = book.for_chat(CHAT)
    queue.add(Track("one", "u1"))
    queue.add(Track("two", "u2"))
    assert queue.remove(1).title == "one"
    assert queue.remove(99) is None
    assert book.for_chat(CHAT) is queue
    book.drop(CHAT)
    assert book.chats() == []


# --- reports --------------------------------------------------------------


def test_report_without_a_reply_asks_for_one(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = reports.build(ctx)
    message = FakeMessage("/report spam")
    run(commands["report"], message)
    assert "Reply to the message" in message.replies[0]
    assert ctx.chats.reports(CHAT) == []


def test_a_report_is_numbered_and_closable(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = reports.build(ctx)
    target = FakeMessage("buy my thing", uid=99)
    message = FakeMessage("/report spam", reply_to=target)
    run(commands["report"], message)
    assert "#1" in message.replies[0]
    assert len(ctx.chats.reports(CHAT)) == 1

    close = FakeMessage("/reports close 1")
    run(commands["reports"], close)
    assert "Report #1 closed" in close.replies[0]
    assert ctx.chats.reports(CHAT) == []


def test_closing_an_unknown_report_says_so(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = reports.build(ctx)
    close = FakeMessage("/reports close 7")
    run(commands["reports"], close)
    assert "no open report #7" in close.replies[0]


def test_appeal_without_text_is_usage(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = reports.build(ctx)
    message = FakeMessage("/appeal")
    run(commands["appeal"], message)
    assert "Usage" in message.replies[0]


# --- posts ----------------------------------------------------------------


def test_post_template_escapes_what_the_member_typed():
    rendered = postmaker.render("{title}\n{body}", "<b>bold</b>", "a & b")
    assert "&lt;b&gt;bold&lt;/b&gt;" in rendered
    assert "a &amp; b" in rendered


def test_post_without_arguments_is_usage(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = postmaker.build(ctx)
    message = FakeMessage("/post")
    run(commands["post"], message)
    assert "Usage" in message.replies[0]


# --- verification ---------------------------------------------------------


def test_verify_button_data_round_trips():
    keyboard = security.button_for(CHAT, OWNER)
    data = keyboard.inline_keyboard[0][0].callback_data
    assert data.startswith("verify:")
    assert security.parse_press(data.split(":", 1)[1]) == (CHAT, OWNER)
    assert security.parse_press("garbage") is None


def test_verify_off_is_stored_and_shown(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.actions = ActionRouter()
    _, commands = security.build(ctx)
    message = FakeMessage("/verify off")
    run(commands["verify"], message)
    assert ctx.chats.get(CHAT, "verify_enabled") is False
    assert "no" in message.replies[0]


def test_verify_timeout_is_clamped(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = security.build(ctx)
    run(commands["verify"], FakeMessage("/verify timeout 500"))
    assert security.timeout_minutes(ctx.chats, CHAT) == security.MAX_TIMEOUT_MINUTES
    run(commands["verify"], FakeMessage("/verify timeout 0"))
    assert security.timeout_minutes(ctx.chats, CHAT) == 1


def test_a_joining_member_is_muted_and_prompted(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.actions = ActionRouter()
    ctx.chats.put(CHAT, "verify_enabled", True)
    _, commands = security.build(ctx)
    client = FakeClient()
    update = SimpleNamespace(
        chat=SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP),
        old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT),
        new_chat_member=SimpleNamespace(
            status=ChatMemberStatus.MEMBER,
            user=SimpleNamespace(id=99, first_name="New", is_bot=False),
        ),
    )
    instance = security.verifier(ctx)
    asyncio.run(instance.on_member_update(client, update))
    assert ("restrict", 99) in client.calls
    assert any(call[0] == "send" for call in client.calls)
    assert (CHAT, 99) in instance.pending
    for task in instance.pending.values():
        task.cancel()


def test_pressing_the_button_verifies_and_clears_the_timer(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.actions = ActionRouter()
    ctx.chats.put(CHAT, "verify_enabled", True)
    security.build(ctx)
    instance = security.verifier(ctx)

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(60))
        instance.pending[(CHAT, 99)] = task
        instance.prompts[(CHAT, 99)] = (CHAT, 777)
        query = FakeQuery(f"verify:{CHAT}:99", 99)
        await instance.on_press(FakeClient(), query, f"{CHAT}:99")
        return task, query

    task, query = asyncio.run(scenario())
    assert task.cancelled()
    assert (CHAT, 99) not in instance.pending
    assert "Verified" in query.answers[0]


def test_someone_else_cannot_press_your_button(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.actions = ActionRouter()
    security.build(ctx)
    instance = security.verifier(ctx)
    query = FakeQuery(f"verify:{CHAT}:99", 1234)
    asyncio.run(instance.on_press(FakeClient(), query, f"{CHAT}:99"))
    assert "someone else" in query.answers[0]


# --- filestore ------------------------------------------------------------


def test_fsave_without_a_document_asks_for_one(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = filestore.build(ctx)
    message = FakeMessage("/fsave")
    run(commands["fsave"], message)
    assert "Reply to a file" in message.replies[0]


def test_get_without_an_id_is_usage(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = filestore.build(ctx)
    message = FakeMessage("/get")
    run(commands["get"], message)
    assert "Usage" in message.replies[0]


def test_get_refuses_a_file_that_is_not_yours(tmp_path):
    ctx = make_ctx(tmp_path)
    _, commands = filestore.build(ctx)
    payload = tmp_path / "note.txt"
    payload.write_text("hello", encoding="utf-8")
    stored = ctx.storage.save_path(4242, payload, name="note.txt")
    message = FakeMessage(f"/get {stored.id}", uid=11)
    run(commands["get"], message)
    assert "not in your vault" in message.replies[0]


# --- the runtime panel must not call an idle plugin "on" -------------------


def test_a_plugin_with_no_commands_is_reported_as_idle(tmp_path):
    """music is enabled but registers nothing without SESSION_STRING."""
    import asyncio
    from types import SimpleNamespace

    from agent.bot import AgentBot
    from agent.config import Settings
    from agent.modules import ops

    settings = Settings.from_env(
        {
            "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
            "API_ID": "1234567",
            "API_HASH": "0123456789abcdef0123456789abcdef",
            "OWNER_ID": str(OWNER),
            "DATA_DIR": str(tmp_path / "data"),
        }
    )
    bot = AgentBot(settings)
    bot.build()

    class Message:
        text = "/plugins"
        id = 1
        chat = SimpleNamespace(id=5)
        from_user = SimpleNamespace(id=OWNER, first_name="Owner")

        def __init__(self):
            self.replies = []

        async def reply(self, text, **_kwargs):
            self.replies.append(str(text))

    _, commands = ops.build(bot.modules)
    message = Message()
    asyncio.run(commands["plugins"](None, message))
    body = message.replies[0]

    assert "idle" in body
    assert "SESSION_STRING" in body          # the reason, not a shrug
    assert "idle" in body.split("<pre>")[1]  # the state column itself
