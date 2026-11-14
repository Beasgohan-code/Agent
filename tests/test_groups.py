"""Filters, welcome and utilities — group features driven by real event objects."""

import asyncio
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

from agent.config import Settings
from agent.modules import filters as filters_module
from agent.modules import utilities, welcome
from agent.platform.chats import ChatStore
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.storage import Storage
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}

ADMIN, MEMBER, LEFT = (
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.LEFT,
)


class FakeChat:
    id = -100900
    type = ChatType.SUPERGROUP
    title = "Test Group"


class FakeClient:
    def __init__(self, *, caller=ADMIN):
        self.calls = []
        self._caller = caller

    async def get_chat_member(self, chat_id, user_id):
        status = self._caller if int(user_id) == 11 else MEMBER
        return SimpleNamespace(
            status=status,
            privileges=SimpleNamespace(
                can_change_info=True, can_restrict_members=True,
                can_delete_messages=True, can_manage_chat=True,
            ),
        )

    async def get_chat_members_count(self, chat_id):
        self.calls.append(("count", chat_id))
        return 42

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("send", chat_id, text))
        return SimpleNamespace(id=1)


class FakeMessage:
    def __init__(self, text="", *, uid=11, target=None):
        self.text = text
        self.chat = FakeChat()
        self.id = 100
        self.from_user = SimpleNamespace(id=uid, first_name="Caller", last_name=None, username="caller")
        self.reply_to_message = (
            SimpleNamespace(from_user=target) if target is not None else None
        )
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


@pytest.fixture()
def ctx(tmp_path):
    return ModuleContext(
        settings=Settings.from_env(ENV),
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        chats=ChatStore(tmp_path),
    )


def run(handler, client, message):
    return asyncio.run(handler(client, message))


def update(*, new_status, old_status, user_id=22, first_name="Newcomer"):
    user = SimpleNamespace(id=user_id, first_name=first_name)
    return SimpleNamespace(
        chat=FakeChat(),
        from_user=user,
        new_chat_member=SimpleNamespace(status=new_status, user=user),
        old_chat_member=SimpleNamespace(status=old_status, user=user),
    )


# --- filters ---------------------------------------------------------------


def test_admin_can_add_list_and_remove_a_filter(ctx):
    client = FakeClient()
    handlers = filters_module.build(ctx)[1]

    saved = FakeMessage("/filter hello Hi there!")
    run(handlers["filter"], client, saved)
    assert ctx.chats.filters(-100900) == {"hello": "Hi there!"}
    assert "saved" in saved.replies[0].lower()

    listing = FakeMessage("/filters")
    run(handlers["filters"], client, listing)
    assert "hello" in listing.replies[0]

    removed = FakeMessage("/stopfilter hello")
    run(handlers["stopfilter"], client, removed)
    assert ctx.chats.filters(-100900) == {}


def test_a_filter_needs_both_a_name_and_a_reply(ctx):
    client = FakeClient()
    message = FakeMessage("/filter lonely")

    run(filters_module.build(ctx)[1]["filter"], client, message)

    assert "Usage" in message.replies[0]


def test_a_member_cannot_manage_filters(ctx):
    client = FakeClient(caller=MEMBER)
    message = FakeMessage("/filter hello hi")

    run(filters_module.build(ctx)[1]["filter"], client, message)

    assert "administrators" in message.replies[0].lower()
    assert ctx.chats.filters(-100900) == {}


def test_the_watcher_answers_a_matching_message(ctx):
    ctx.chats.set_filter(-100900, "hello", "Hi there!", by=11)
    watch = filters_module.watch(ctx)
    message = FakeMessage("well hello everyone")

    asyncio.run(watch(None, message))

    assert message.replies == ["Hi there!"]


def test_the_watcher_stays_quiet_for_commands_and_misses(ctx):
    ctx.chats.set_filter(-100900, "hello", "Hi there!", by=11)
    watch = filters_module.watch(ctx)

    command = FakeMessage("/hello")
    asyncio.run(watch(None, command))
    assert command.replies == []

    unrelated = FakeMessage("good morning")
    asyncio.run(watch(None, unrelated))
    assert unrelated.replies == []


# --- welcome ---------------------------------------------------------------


def test_setwelcome_requires_admin(ctx):
    client = FakeClient(caller=MEMBER)
    message = FakeMessage("/setwelcome Welcome {mention}!")

    run(welcome.build(ctx)[1]["setwelcome"], client, message)

    assert "administrators" in message.replies[0].lower()
    assert ctx.chats.greeting(-100900, "welcome")["text"] == ""


def test_a_join_sends_the_rendered_greeting(ctx):
    ctx.chats.set_greeting(-100900, "welcome", "Welcome {mention} to {chat}, member #{count}")
    client = FakeClient()

    asyncio.run(welcome.watch(ctx)(client, update(new_status=MEMBER, old_status=LEFT)))

    sends = [call for call in client.calls if call[0] == "send"]
    assert len(sends) == 1
    _kind, chat_id, text = sends[0]
    assert chat_id == -100900
    assert "tg://user?id=22" in text
    assert "Test Group" in text
    assert "42" in text


def test_no_greeting_until_one_is_set(ctx):
    client = FakeClient()

    asyncio.run(welcome.watch(ctx)(client, update(new_status=MEMBER, old_status=LEFT)))

    assert client.calls == []


def test_a_leave_sends_the_goodbye(ctx):
    ctx.chats.set_greeting(-100900, "goodbye", "Bye {name}")
    client = FakeClient()

    asyncio.run(welcome.watch(ctx)(client, update(new_status=LEFT, old_status=MEMBER)))

    sends = [call for call in client.calls if call[0] == "send"]
    assert sends[0][2] == "Bye Newcomer"


def test_promotions_do_not_trigger_greetings(ctx):
    ctx.chats.set_greeting(-100900, "welcome", "Welcome {mention}")
    client = FakeClient()

    asyncio.run(
        welcome.watch(ctx)(client, update(new_status=ADMIN, old_status=MEMBER))
    )

    assert client.calls == []


def test_welcome_toggle(ctx):
    client = FakeClient()
    handlers = welcome.build(ctx)[1]
    ctx.chats.set_greeting(-100900, "welcome", "hi {mention}")

    run(handlers["welcome"], client, FakeMessage("/welcome off"))

    assert ctx.chats.greeting(-100900, "welcome")["enabled"] is False


# --- utilities -------------------------------------------------------------


def test_id_reports_the_real_identifiers(ctx):
    client = FakeClient()
    message = FakeMessage("/id", target=SimpleNamespace(id=77, first_name="T"))

    run(utilities.build(ctx)[1]["id"], client, message)

    body = message.replies[0]
    assert "-100900" in body
    assert ">11<" in body
    assert ">77<" in body


def test_info_reads_membership_from_telegram(ctx):
    client = FakeClient()
    message = FakeMessage("/info", target=SimpleNamespace(id=22, first_name="Ada", last_name=None, username=None))

    run(utilities.build(ctx)[1]["info"], client, message)

    assert "Status here: Member" in message.replies[0]


def test_time_reports_utc(ctx):
    client = FakeClient()
    message = FakeMessage("/time")

    run(utilities.build(ctx)[1]["time"], client, message)

    assert "UTC" in message.replies[0]
