"""The owner log channel: hashtags, routing, and what triggers each event."""

import asyncio
from types import SimpleNamespace

from pyrogram.enums import ChatMemberStatus, ChatType

from agent.config import Settings
from agent.handlers.commands import CommandHandlers
from agent.modules import ops
from agent.platform.audience import UserIndex
from agent.platform.events import EventLog
from agent.platform.logbook import LogBook, format_event, tag_for
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


class FakeClient:
    def __init__(self, *, reachable=True):
        self.sent = []
        self._reachable = reachable
        self.me = SimpleNamespace(id=999)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return SimpleNamespace(id=1)

    async def get_chat(self, chat_id):
        if not self._reachable:
            raise RuntimeError("chat not found")
        return SimpleNamespace(id=chat_id, title="Log Channel")


class FakeMessage:
    def __init__(self, text="", *, uid=11, chat_id=7, chat_type=ChatType.CHANNEL,
                 first_name="Owner", username="owner"):
        self.text = text
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.from_user = SimpleNamespace(id=uid, first_name=first_name, username=username)
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


class FakeSender:
    async def send(self, chat_id, screen):
        return SimpleNamespace(id=1)


# --- formatting ------------------------------------------------------------


def test_events_are_tagged_with_a_searchable_hashtag():
    assert tag_for("new_user") == "NewUser"
    assert tag_for("new_group") == "NewGroup"
    assert tag_for("start") == "BotStarted"
    assert tag_for("restart") == "Restart"
    assert tag_for("something_custom") == "SomethingCustom"


def test_a_formatted_event_leads_with_its_hashtag():
    body = format_event("new_group", {"title": "Testers", "id": -1001})

    assert body.startswith("<b>#NewGroup</b>")
    assert "Testers" in body
    assert "-1001" in body


def test_empty_fields_are_not_rendered():
    body = format_event("plugin", {"slug": "encoder", "reason": ""})

    assert "encoder" in body
    assert "reason" not in body


# --- routing ---------------------------------------------------------------


def test_events_go_to_the_channel_when_one_is_set(tmp_path):
    client = FakeClient()
    logbook = LogBook(tmp_path, channel_id=-1001, owner_id=11)
    logbook.client = client

    assert asyncio.run(logbook.post("new_user", uid=5)) is True
    assert client.sent[0][0] == -1001
    assert "#NewUser" in client.sent[0][1]


def test_events_fall_back_to_the_owner_dm(tmp_path):
    client = FakeClient()
    logbook = LogBook(tmp_path, channel_id=None, owner_id=11)
    logbook.client = client

    asyncio.run(logbook.post("new_group", title="Group"))

    assert client.sent[0][0] == 11


def test_nowhere_to_send_is_reported_honestly(tmp_path):
    logbook = LogBook(tmp_path)
    logbook.client = FakeClient()

    assert logbook.destination() is None
    assert asyncio.run(logbook.post("new_user", uid=5)) is False


def test_a_failed_post_does_not_raise(tmp_path):
    class Broken:
        me = SimpleNamespace(id=999)

        async def send_message(self, *args, **kwargs):
            raise RuntimeError("flood")

    logbook = LogBook(tmp_path, channel_id=-1001)
    logbook.client = Broken()

    assert asyncio.run(logbook.post("new_user", uid=5)) is False


def test_the_channel_choice_survives_a_restart(tmp_path):
    first = LogBook(tmp_path, channel_id=-1001)
    first.set_channel(-2002)

    reloaded = LogBook(tmp_path, channel_id=-9999)

    assert reloaded.channel_id == -2002


def test_the_event_log_feeds_the_channel(tmp_path):
    client = FakeClient()
    logbook = LogBook(tmp_path, channel_id=-1001)
    logbook.client = client
    events = EventLog()
    events.subscribe(lambda kind, fields: logbook.publish(kind, fields))

    async def scenario():
        events.emit("plugin", slug="encoder", action="off")
        await asyncio.sleep(0)  # let the scheduled post run

    asyncio.run(scenario())

    assert client.sent and "#Plugin" in client.sent[0][1]


# --- triggers --------------------------------------------------------------


def test_first_start_is_a_new_user_and_the_second_is_returning(tmp_path):
    events = EventLog()
    users = UserIndex(tmp_path)
    handlers = CommandHandlers(
        FakeSender(), Theme(), events=events, users=users
    )
    message = FakeMessage("/start", uid=42)

    asyncio.run(handlers.start(None, message))
    asyncio.run(handlers.start(None, message))

    kinds = [event["kind"] for event in events.recent(5)]
    assert kinds.count("new_user") == 1
    assert kinds.count("returning_user") == 1


def test_the_user_index_only_stores_ids(tmp_path):
    users = UserIndex(tmp_path)
    users.remember(42)

    stored = (tmp_path / "users.json").read_text()

    assert "42" in stored
    assert "owner" not in stored


def test_being_added_to_a_group_is_logged(tmp_path):
    events = EventLog()
    ctx = SimpleNamespace(events=events)
    watcher = ops.extra_handlers(ctx)[0].callback  # the ChatMemberUpdated handler

    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1001, type=ChatType.SUPERGROUP, title="New Group"),
        from_user=SimpleNamespace(id=11),
        new_chat_member=SimpleNamespace(
            status=ChatMemberStatus.MEMBER, user=SimpleNamespace(id=999)
        ),
        old_chat_member=SimpleNamespace(
            status=ChatMemberStatus.LEFT, user=SimpleNamespace(id=999)
        ),
    )
    client = FakeClient()

    asyncio.run(watcher(client, update))

    event = events.recent(1)[0]
    assert event["kind"] == "new_group"
    assert event["title"] == "New Group"


def test_a_member_joining_is_not_a_new_group(tmp_path):
    events = EventLog()
    ctx = SimpleNamespace(events=events)
    watcher = ops.extra_handlers(ctx)[0].callback

    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1001, type=ChatType.SUPERGROUP, title="Group"),
        from_user=SimpleNamespace(id=11),
        new_chat_member=SimpleNamespace(
            status=ChatMemberStatus.MEMBER, user=SimpleNamespace(id=555)
        ),
        old_chat_member=SimpleNamespace(
            status=ChatMemberStatus.LEFT, user=SimpleNamespace(id=555)
        ),
    )

    asyncio.run(watcher(FakeClient(), update))

    assert events.recent(1) == []


# --- /setlog ---------------------------------------------------------------


def make_ctx(tmp_path, client, *, owner_id=11):
    logbook = LogBook(tmp_path, channel_id=None, owner_id=owner_id)
    logbook.client = client
    return SimpleNamespace(
        settings=Settings.from_env({**ENV, "OWNER_ID": str(owner_id)}),
        events=EventLog(),
        logbook=logbook,
        jobs=None,
        links=None,
        storage=None,
        monitor=None,
        runtime=None,
        lease=None,
    )


def test_setlog_stores_a_reachable_channel(tmp_path):
    client = FakeClient()
    ctx = make_ctx(tmp_path, client)

    message = FakeMessage("/setlog -100777")
    asyncio.run(ops.build(ctx)[1]["setlog"](client, message))

    assert ctx.logbook.channel_id == -100777
    assert "Log channel set" in message.replies[0]


def test_setlog_refuses_an_unreachable_channel(tmp_path):
    client = FakeClient(reachable=False)
    ctx = make_ctx(tmp_path, client)

    message = FakeMessage("/setlog -100777")
    asyncio.run(ops.build(ctx)[1]["setlog"](client, message))

    assert ctx.logbook.channel_id is None
    assert "cannot reach" in message.replies[0]


def test_setlog_here_requires_a_channel_chat(tmp_path):
    client = FakeClient()
    ctx = make_ctx(tmp_path, client)

    private = FakeMessage("/setlog here", chat_type=ChatType.PRIVATE)
    asyncio.run(ops.build(ctx)[1]["setlog"](client, private))
    assert "inside the channel" in private.replies[0]

    channel = FakeMessage("/setlog here", chat_type=ChatType.CHANNEL, chat_id=-1005)
    asyncio.run(ops.build(ctx)[1]["setlog"](client, channel))
    assert ctx.logbook.channel_id == -1005


def test_setlog_is_owner_only(tmp_path):
    client = FakeClient()
    ctx = make_ctx(tmp_path, client)

    message = FakeMessage("/setlog -100777", uid=404)
    asyncio.run(ops.build(ctx)[1]["setlog"](client, message))

    assert ctx.logbook.channel_id is None
    assert message.replies == [ops.OWNER_ONLY]


def test_log_reports_the_destination(tmp_path):
    client = FakeClient()
    ctx = make_ctx(tmp_path, client)
    ctx.logbook.set_channel(-100777)
    ctx.events.emit("new_user", uid=5)

    message = FakeMessage("/log")
    asyncio.run(ops.build(ctx)[1]["log"](client, message))

    body = message.replies[0]
    assert "-100777" in body
    assert "#NewUser" in body


def test_close_drains_stop_post_before_disconnect_and_rejects_late_events(tmp_path):
    async def scenario():
        client = FakeClient()
        book = LogBook(tmp_path, channel_id=-1001)
        book.client = client
        book.publish('stop', {})
        await book.close()
        assert len(client.sent) == 1 and '#BotStopped' in client.sent[0][1]
        assert book.client is None and not book._pending
        book.publish('error', {'reason': 'late'})
        await book.close()
        assert len(client.sent) == 1
    asyncio.run(scenario())


def test_close_cancels_hung_posts_without_draining_another_bot(tmp_path):
    async def scenario():
        from unittest.mock import AsyncMock
        entered = asyncio.Event()
        async def hung(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        first = LogBook(tmp_path / 'first', channel_id=-1001)
        second = LogBook(tmp_path / 'second', channel_id=-1002)
        first.client = SimpleNamespace(send_message=AsyncMock(side_effect=hung))
        second_client = FakeClient()
        second.client = second_client
        first.publish('stop', {})
        await entered.wait()
        await first.close(timeout=0.001)
        second.publish('start', {})
        await second.close()
        assert not first._pending and not second._pending
        assert '#BotStarted' in second_client.sent[0][1]
    asyncio.run(scenario())


def test_cancelled_close_detaches_client_and_cancels_pending_posts(tmp_path):
    async def scenario():
        from unittest.mock import AsyncMock
        entered = asyncio.Event()
        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        book = LogBook(tmp_path, channel_id=-1001)
        book.client = SimpleNamespace(send_message=AsyncMock(side_effect=blocked))
        book.publish('stop', {})
        await entered.wait()
        closer = asyncio.create_task(book.close(timeout=30))
        await asyncio.sleep(0)
        closer.cancel()
        await asyncio.gather(closer, return_exceptions=True)
        assert book.client is None and not book._pending
    asyncio.run(scenario())


def test_logbook_pending_queue_is_bounded_per_bot(tmp_path, monkeypatch):
    async def scenario():
        from unittest.mock import AsyncMock
        monkeypatch.setattr('agent.platform.logbook.MAX_PENDING', 2)
        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()
        book = LogBook(tmp_path, channel_id=-1001)
        book.client = SimpleNamespace(send_message=AsyncMock(side_effect=blocked))
        for _ in range(5):
            book.publish('plugin', {})
        assert len(book._pending) == 2 and book.dropped == 3
        await book.close(timeout=0)
        assert not book._pending
    asyncio.run(scenario())
