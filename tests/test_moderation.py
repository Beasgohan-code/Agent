"""Moderation handlers against a fake client and a real chat store."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

from agent.config import Settings
from agent.modules import moderation
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

ADMIN, MEMBER, OWNER = (
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.OWNER,
)


def member(status, **rights):
    privileges = SimpleNamespace(
        can_restrict_members=rights.get("can_restrict_members", True),
        can_delete_messages=rights.get("can_delete_messages", True),
        can_manage_chat=rights.get("can_manage_chat", True),
    )
    return SimpleNamespace(status=status, privileges=privileges)


class FakeClient:
    def __init__(self, *, caller=ADMIN, target=MEMBER, rights=None):
        self.calls = []
        self._caller = caller
        self._target = target
        self._rights = rights or {}

    async def get_chat_member(self, chat_id, user_id):
        status = self._caller if int(user_id) == 11 else self._target
        return member(status, **self._rights)

    async def ban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("ban", int(user_id)))

    async def unban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("unban", int(user_id)))

    async def restrict_chat_member(self, chat_id, user_id, permissions, **kwargs):
        self.calls.append(("restrict", int(user_id), permissions, kwargs.get("until_date")))

    async def delete_messages(self, chat_id, message_ids, **kwargs):
        self.calls.append(("delete", message_ids))


class FakeChat:
    id = -100500
    type = ChatType.SUPERGROUP


class FakeSent:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeMessage:
    def __init__(self, text="", *, uid=11, target_uid=22, reply=False, message_id=100):
        self.text = text
        self.chat = FakeChat()
        self.id = message_id
        self.from_user = SimpleNamespace(id=uid, first_name="Caller")
        self.reply_to_message = (
            SimpleNamespace(from_user=SimpleNamespace(id=target_uid, first_name="Target"))
            if reply
            else None
        )
        self.replies = []
        self.deleted = False

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return FakeSent()

    async def delete(self):
        self.deleted = True


@pytest.fixture()
def ctx(tmp_path):
    settings = Settings.from_env(ENV)
    return ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        chats=ChatStore(tmp_path),
    )


@pytest.fixture(autouse=True)
def no_purge_delay(monkeypatch):
    monkeypatch.setattr(moderation, "PURGE_CONFIRM_TTL", 0)


def run(handler, client, message):
    return asyncio.run(handler(client, message))


def handlers(ctx):
    return moderation.build(ctx)[1]


# --- permissions -----------------------------------------------------------


def test_a_plain_member_cannot_warn(ctx):
    client = FakeClient(caller=MEMBER)
    message = FakeMessage("/warn 22 being rude")

    run(handlers(ctx)["warn"], client, message)

    assert message.replies == [moderation.DENIED]
    assert ctx.chats.active_warning_count(-100500, 22) == 0


def test_an_admin_holding_the_privilege_can_mute(ctx):
    client = FakeClient(caller=ADMIN, rights={"can_restrict_members": True})
    message = FakeMessage("/mute 10m", reply=True)

    run(handlers(ctx)["mute"], client, message)

    kind, user_id, permissions, until_date = client.calls[0]
    assert (kind, user_id) == ("restrict", 22)
    assert permissions.can_send_messages is False
    # pyrogram wants a datetime, and the mute must actually expire.
    assert isinstance(until_date, datetime)
    assert until_date > datetime.now(timezone.utc)
    assert "Member muted" in message.replies[0]


def test_an_admin_without_the_privilege_is_refused(ctx):
    client = FakeClient(caller=ADMIN, rights={"can_restrict_members": False})
    message = FakeMessage("/ban 22")

    run(handlers(ctx)["ban"], client, message)

    assert message.replies == [moderation.DENIED]
    assert client.calls == []


def test_the_bot_owner_acts_without_being_an_admin(tmp_path):
    settings = Settings.from_env({**ENV, "OWNER_ID": "11"})
    owner_ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "s"),
        links=LinkStore(tmp_path / "l", "secret"),
        chats=ChatStore(tmp_path),
    )
    client = FakeClient(caller=MEMBER)
    message = FakeMessage("/warn 22 spam")

    run(handlers(owner_ctx)["warn"], client, message)

    assert owner_ctx.chats.active_warning_count(-100500, 22) == 1


# --- target safety ---------------------------------------------------------


def test_administrators_are_not_moderated(ctx):
    client = FakeClient(caller=ADMIN, target=ADMIN)
    message = FakeMessage("/ban 22")

    run(handlers(ctx)["ban"], client, message)

    assert "cannot act on an administrator" in message.replies[0]
    assert ("ban", 22) not in client.calls


def test_kick_bans_then_unbans(ctx):
    client = FakeClient(caller=ADMIN)
    message = FakeMessage("/kick", reply=True)

    run(handlers(ctx)["kick"], client, message)

    assert client.calls == [("ban", 22), ("unban", 22)]
    assert "Member kicked" in message.replies[0]


def test_ban_records_reason_and_log(ctx):
    client = FakeClient(caller=ADMIN)
    message = FakeMessage("/ban 22 advertising")

    run(handlers(ctx)["ban"], client, message)

    assert ("ban", 22) in client.calls
    assert "advertising" in message.replies[0]
    assert ctx.chats.history(-100500)[0]["action"] == "ban"


# --- warnings --------------------------------------------------------------


def test_warn_then_warnings_then_unwarn(ctx):
    client = FakeClient(caller=ADMIN)
    run(handlers(ctx)["warn"], client, FakeMessage("/warn 22 first offence"))

    listing = FakeMessage("/warnings 22")
    run(handlers(ctx)["warnings"], client, listing)
    assert "first offence" in listing.replies[0]

    run(handlers(ctx)["unwarn"], client, FakeMessage("/unwarn 22"))
    assert ctx.chats.active_warning_count(-100500, 22) == 0


def test_unwarn_without_warnings_says_so(ctx):
    client = FakeClient(caller=ADMIN)
    message = FakeMessage("/unwarn 22")

    run(handlers(ctx)["unwarn"], client, message)

    assert "no active warnings" in message.replies[0]


def test_note_is_stored_and_surfaced_by_warnings(ctx):
    client = FakeClient(caller=ADMIN)
    run(handlers(ctx)["note"], client, FakeMessage("/note 22 watch this one"))

    listing = FakeMessage("/warnings 22")
    run(handlers(ctx)["warnings"], client, listing)

    assert ctx.chats.note_of(-100500, 22) == "watch this one"
    assert "watch this one" in listing.replies[0]


def test_trust_toggles(ctx):
    client = FakeClient(caller=ADMIN)

    run(handlers(ctx)["trust"], client, FakeMessage("/trust", reply=True))
    assert ctx.chats.is_trusted(-100500, 22) is True

    run(handlers(ctx)["trust"], client, FakeMessage("/trust", reply=True))
    assert ctx.chats.is_trusted(-100500, 22) is False


# --- purge -----------------------------------------------------------------


def test_purge_deletes_the_requested_range(ctx):
    client = FakeClient(caller=ADMIN)
    message = FakeMessage("/purge 3", message_id=100)

    run(handlers(ctx)["purge"], client, message)

    deleted = [c[1] for c in client.calls if c[0] == "delete"]
    assert deleted == [99, 98, 97]
    assert "Messages removed: 3" in message.replies[0]


def test_purge_is_capped(ctx):
    client = FakeClient(caller=ADMIN)

    run(handlers(ctx)["purge"], client, FakeMessage("/purge 9999", message_id=1000))

    assert len([c for c in client.calls if c[0] == "delete"]) == moderation.MAX_PURGE


# --- anti-spam -------------------------------------------------------------


def test_antispam_off_is_persisted(ctx):
    client = FakeClient(caller=ADMIN)

    run(handlers(ctx)["antispam"], client, FakeMessage("/antispam off"))

    policy = ctx.chats.antispam(-100500)
    assert policy["flood_enabled"] is False
    assert policy["links_enabled"] is False


def test_antispam_rejects_junk(ctx):
    client = FakeClient(caller=ADMIN)
    message = FakeMessage("/antispam explode")

    run(handlers(ctx)["antispam"], client, message)

    assert "Usage:" in message.replies[0]


def test_antispam_blocks_links_and_deletes_the_message(ctx):
    client = FakeClient(caller=MEMBER)
    ctx.chats.save_antispam(-100500, {**ctx.chats.antispam(-100500), "action": "delete"})
    watch = moderation.watch(ctx)

    message = FakeMessage("join here https://spam.example now")

    asyncio.run(watch(client, message))

    assert message.deleted is True


def test_antispam_flood_mutes_at_the_limit(ctx):
    client = FakeClient(caller=MEMBER)
    policy = ctx.chats.antispam(-100500)
    policy.update({"action": "mute", "mute_seconds": 60, "links_enabled": False})
    ctx.chats.save_antispam(-100500, policy)
    watch = moderation.watch(ctx)

    for index in range(policy["flood_messages"] + 1):
        asyncio.run(watch(client, FakeMessage(f"message number {index}")))

    kinds = [c[0] for c in client.calls]
    assert "restrict" in kinds
    assert any(entry["action"] == "antispam:mute" for entry in ctx.chats.history(-100500))


def test_antispam_ignores_trusted_and_staff(ctx):
    client = FakeClient(caller=MEMBER)
    ctx.chats.save_antispam(-100500, {**ctx.chats.antispam(-100500), "action": "ban"})
    ctx.chats.toggle_trust(-100500, 11)
    watch = moderation.watch(ctx)

    asyncio.run(watch(client, FakeMessage("trusted https://fine.example")))

    assert client.calls == []


def test_antispam_does_not_store_message_text(tmp_path):
    settings = Settings.from_env(ENV)
    ctx2 = ModuleContext(
        settings=settings, theme=Theme(), sender=None, jobs=JobQueue(),
        storage=Storage(tmp_path / "s2"), links=LinkStore(tmp_path / "l2", "s"),
        chats=ChatStore(tmp_path / "state"),
    )
    watch = moderation.watch(ctx2)
    client = FakeClient(caller=MEMBER)

    asyncio.run(watch(client, FakeMessage("something unremarkable")))

    path = tmp_path / "state" / "chats.json"
    assert not path.exists() or "unremarkable" not in path.read_text()


# --- modlog ----------------------------------------------------------------


def test_modlog_lists_recent_actions(ctx):
    client = FakeClient(caller=ADMIN)
    run(handlers(ctx)["warn"], client, FakeMessage("/warn 22 noisy"))

    message = FakeMessage("/modlog")
    run(handlers(ctx)["modlog"], client, message)

    assert "WARN" in message.replies[0]
    assert "noisy" in message.replies[0]


# Recovery commands must respect group defaults, not a generic open policy.
def test_unmute_uses_current_group_permissions(ctx):
    from pyrogram.types import ChatPermissions
    baseline = ChatPermissions(can_send_messages=True, can_send_photos=False,
                               can_invite_users=False)
    class Client(FakeClient):
        async def get_chat(self, chat_id):
            return SimpleNamespace(permissions=baseline)
    client = Client()
    run(handlers(ctx)['unmute'], client, FakeMessage('/unmute', reply=True))
    assert client.calls[0][2] is baseline
    assert client.calls[0][2].can_send_photos is False


def test_unmute_refuses_when_group_permissions_are_unknown(ctx):
    class Client(FakeClient):
        async def get_chat(self, chat_id):
            return SimpleNamespace(permissions=None)
    client = Client()
    message = FakeMessage('/unmute', reply=True)
    run(handlers(ctx)['unmute'], client, message)
    assert not client.calls
    assert 'Cannot read' in message.replies[0]


def test_unmute_protects_administrators(ctx):
    client = FakeClient(target=ADMIN)
    message = FakeMessage('/unmute', reply=True)
    run(handlers(ctx)['unmute'], client, message)
    assert not client.calls
    assert 'administrator' in message.replies[0]


@pytest.mark.parametrize('command', ['mute', 'unmute', 'kick', 'ban', 'unban'])
def test_restriction_commands_report_api_permission_failures(ctx, command):
    from pyrogram.errors import ChatAdminRequired
    class Refusing(FakeClient):
        async def restrict_chat_member(self, *args, **kwargs):
            raise ChatAdminRequired()
        async def ban_chat_member(self, *args, **kwargs):
            raise ChatAdminRequired()
        async def unban_chat_member(self, *args, **kwargs):
            raise ChatAdminRequired()
        async def get_chat(self, chat_id):
            raise ChatAdminRequired()
    message = FakeMessage('/' + command, reply=True)
    run(handlers(ctx)[command], Refusing(), message)
    assert 'ChatAdminRequired' in message.replies[-1]
    assert 'not confirmed' in message.replies[-1]
    assert not ctx.chats.history(-100500)


def test_ban_reports_flood_wait_without_blocking_or_retry(ctx):
    from pyrogram.errors import FloodWait
    class Limited(FakeClient):
        async def ban_chat_member(self, *args, **kwargs):
            raise FloodWait(42)
    client = Limited()
    message = FakeMessage('/ban', reply=True)
    run(handlers(ctx)['ban'], client, message)
    assert '42 seconds' in message.replies[-1]
    assert not client.calls
