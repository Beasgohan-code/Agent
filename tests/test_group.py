"""Group management: panel, rules, pinning, admin list, warn threshold, lockdown."""

import asyncio
import html
import re
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

from agent.config import Settings
from agent.modules import group, moderation
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

CHAT = -100500
ADMIN, MEMBER, OWNER = (
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.OWNER,
)
PRE_RE = re.compile(r"<pre>([\s\S]*?)</pre>")


def member(status, **rights):
    privileges = SimpleNamespace(
        can_restrict_members=rights.get("can_restrict_members", True),
        can_delete_messages=rights.get("can_delete_messages", True),
        can_manage_chat=rights.get("can_manage_chat", True),
        can_change_info=rights.get("can_change_info", True),
        can_pin_messages=rights.get("can_pin_messages", True),
    )
    return SimpleNamespace(status=status, privileges=privileges)


class FakeClient:
    def __init__(self, *, caller=ADMIN, target=MEMBER, rights=None, admins=None, fail_admins=False):
        self.calls = []
        self._caller = caller
        self._target = target
        self._rights = rights or {}
        self._admins = admins if admins is not None else [
            (OWNER, 11, "Owner", None),
            (ADMIN, 22, "Target", "boss"),
        ]
        self._fail_admins = fail_admins

    async def get_chat_member(self, chat_id, user_id):
        status = self._caller if int(user_id) == 11 else self._target
        return member(status, **self._rights)

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        self.calls.append(("pin", int(message_id), kwargs))

    async def unpin_chat_message(self, chat_id, message_id=0, **kwargs):
        self.calls.append(("unpin", int(message_id)))

    async def unpin_all_chat_messages(self, chat_id, **kwargs):
        self.calls.append(("unpin_all", None))

    async def restrict_chat_member(self, chat_id, user_id, permissions, **kwargs):
        self.calls.append(("restrict", int(user_id)))

    async def ban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("ban", int(user_id)))

    async def unban_chat_member(self, chat_id, user_id, **kwargs):
        self.calls.append(("unban", int(user_id)))

    async def get_chat(self, chat_id):
        from pyrogram.types import ChatPermissions
        return SimpleNamespace(permissions=ChatPermissions(
            can_send_messages=True, can_send_photos=False,
            can_invite_users=False, can_pin_messages=False,
        ))

    async def set_chat_permissions(self, chat_id, permissions):
        self.calls.append(("permissions", permissions))
        return SimpleNamespace(id=chat_id)

    def get_chat_members(self, chat_id, filter=None, **kwargs):
        if self._fail_admins:
            raise RuntimeError("CHAT_ADMIN_REQUIRED")

        async def iterator():
            for status, uid, first, custom in self._admins:
                yield SimpleNamespace(
                    status=status,
                    custom_title=custom,
                    user=SimpleNamespace(id=uid, first_name=first, last_name=None, username=None),
                )

        return iterator()


class FakeChat:
    id = CHAT
    type = ChatType.SUPERGROUP
    title = "Test Group"


class FakeSent:
    async def delete(self):
        pass


class FakeMessage:
    def __init__(self, text="", *, uid=11, reply=False, reply_id=555, reply_text=""):
        self.text = text
        self.chat = FakeChat()
        self.id = 900
        self.from_user = SimpleNamespace(id=uid, first_name="Caller")
        self.reply_to_message = (
            SimpleNamespace(
                id=reply_id,
                from_user=SimpleNamespace(id=22, first_name="Target"),
                text=reply_text,
            )
            if reply
            else None
        )
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return FakeSent()


@pytest.fixture()
def ctx(tmp_path):
    # No OWNER_ID: these tests exercise Telegram rights, and an owner shortcut
    # would let every call through.
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


def run(handler, client, message):
    return asyncio.run(handler(client, message))


def handlers(ctx):
    return group.build(ctx)[1]


CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)


def pre(markup: str) -> str:
    """The table content (entities resolved), native ``<table>`` or ``<pre>`` grid."""
    if "<table" in markup:
        return html.unescape(" ".join(CELL_RE.findall(markup)))
    match = PRE_RE.search(markup)
    return html.unescape(match.group(1)) if match else ""


# --- permissions -----------------------------------------------------------


def test_a_plain_member_cannot_open_the_settings_panel(ctx):
    message = FakeMessage("/settings")

    run(handlers(ctx)["settings"], FakeClient(caller=MEMBER), message)

    assert message.replies == [moderation.DENIED]


def test_an_admin_without_change_info_is_refused(ctx):
    message = FakeMessage("/settings")

    run(handlers(ctx)["settings"], FakeClient(rights={"can_change_info": False}), message)

    assert message.replies == [moderation.DENIED]


# --- /settings -------------------------------------------------------------


def test_settings_show_live_values_in_a_table(ctx):
    ctx.chats.save_antispam(CHAT, {**ctx.chats.antispam(CHAT), "action": "mute", "flood_messages": 9})
    ctx.chats.put(CHAT, "warn_limit", 5)
    ctx.chats.put(CHAT, "warn_action", "ban")
    ctx.chats.set_greeting(CHAT, "welcome", "hi {name}")
    ctx.chats.toggle_trust(CHAT, 22)
    message = FakeMessage("/settings")

    run(handlers(ctx)["settings"], FakeClient(), message)

    body = message.replies[0]
    table = pre(body)
    assert "mute" in table and "9" in table       # anti-spam action and flood limit
    assert "5 -> ban" in table                    # warn threshold as configured
    assert "on" in table                          # welcome enabled
    assert str(CHAT) in body                      # this chat's id
    assert "Approved" in table and "1" in table


def test_settings_report_the_log_channel_and_rules_state(ctx):
    ctx.chats.put(CHAT, "rules", "be nice")
    message = FakeMessage("/settings")

    run(handlers(ctx)["settings"], FakeClient(), message)

    assert "7 chars" in pre(message.replies[0])


# --- /rules ----------------------------------------------------------------


def test_rules_without_rules_explains_how_to_add_them(ctx):
    message = FakeMessage("/rules")

    run(handlers(ctx)["rules"], FakeClient(caller=MEMBER), message)

    assert "no rules stored" in message.replies[0]


def test_setrules_stores_the_text_and_rules_shows_it(ctx):
    setter = FakeMessage("/setrules Be kind. No spam.")
    run(handlers(ctx)["setrules"], FakeClient(), setter)
    assert "saved" in setter.replies[0]

    reader = FakeMessage("/rules")
    run(handlers(ctx)["rules"], FakeClient(caller=MEMBER), reader)
    assert "Be kind. No spam." in reader.replies[0]


def test_setrules_can_take_the_replied_message(ctx):
    message = FakeMessage("/setrules", reply=True, reply_text="Rule from a reply")
    run(handlers(ctx)["setrules"], FakeClient(), message)

    assert ctx.chats.get(CHAT, "rules") == "Rule from a reply"


def test_setrules_clear_removes_them(ctx):
    ctx.chats.put(CHAT, "rules", "old rules")
    message = FakeMessage("/setrules clear")

    run(handlers(ctx)["setrules"], FakeClient(), message)

    assert ctx.chats.get(CHAT, "rules") == ""
    assert "cleared" in message.replies[0]


def test_setrules_refuses_oversized_text(ctx):
    message = FakeMessage("/setrules " + "x" * (group.MAX_RULES + 1))

    run(handlers(ctx)["setrules"], FakeClient(), message)

    assert "too long" in message.replies[0]
    assert ctx.chats.get(CHAT, "rules") in (None, "")


def test_setrules_without_text_shows_usage(ctx):
    message = FakeMessage("/setrules")

    run(handlers(ctx)["setrules"], FakeClient(), message)

    assert "Usage" in message.replies[0]


# --- pinning ---------------------------------------------------------------


def test_pin_requires_a_reply(ctx):
    message = FakeMessage("/pin")

    run(handlers(ctx)["pin"], FakeClient(), message)

    assert "Reply to the message" in message.replies[0]


def test_pin_pins_the_replied_message(ctx):
    client = FakeClient()
    message = FakeMessage("/pin", reply=True, reply_id=42)

    run(handlers(ctx)["pin"], client, message)

    assert client.calls == [("pin", 42, {"disable_notification": False, "both_sides": True})]
    assert "pinned" in message.replies[0].lower()


def test_pin_silent_disables_the_notification(ctx):
    client = FakeClient()
    message = FakeMessage("/pin silent", reply=True, reply_id=42)

    run(handlers(ctx)["pin"], client, message)

    assert client.calls[0][2]["disable_notification"] is True
    assert "No notification" in message.replies[0]


def test_pin_reports_a_refusal_instead_of_claiming_success(ctx):
    class Refusing(FakeClient):
        async def pin_chat_message(self, *args, **kwargs):
            raise RuntimeError("CHAT_ADMIN_REQUIRED")

    message = FakeMessage("/pin", reply=True)

    run(handlers(ctx)["pin"], Refusing(), message)

    assert "Could not pin" in message.replies[0]


def test_unpin_all_unpins_everything(ctx):
    client = FakeClient()
    message = FakeMessage("/unpin all")

    run(handlers(ctx)["unpin"], client, message)

    assert ("unpin_all", None) in client.calls


def test_unpin_without_a_reply_unpins_the_latest(ctx):
    client = FakeClient()
    message = FakeMessage("/unpin")

    run(handlers(ctx)["unpin"], client, message)

    assert client.calls == [("unpin", 0)]


# --- /admins ---------------------------------------------------------------


def test_admins_lists_roles_and_ids(ctx):
    message = FakeMessage("/admins")

    run(handlers(ctx)["admins"], FakeClient(), message)

    table = pre(message.replies[0])
    assert "creator" in table and "admin" in table
    assert "Owner" in table and "11" in table


def test_admins_reports_a_failure_rather_than_an_empty_list(ctx):
    message = FakeMessage("/admins")

    run(handlers(ctx)["admins"], FakeClient(fail_admins=True), message)

    assert "Could not read the administrator list" in message.replies[0]


def test_admins_caps_the_table_and_says_how_many_were_hidden(ctx):
    admins = [(ADMIN, 100 + index, f"Admin{index}", None) for index in range(20)]
    message = FakeMessage("/admins")

    run(handlers(ctx)["admins"], FakeClient(admins=admins), message)

    assert "Plus 5 more." in message.replies[0]


# --- /warnlimit ------------------------------------------------------------


def test_warnlimit_reports_the_default(ctx):
    message = FakeMessage("/warnlimit")

    run(handlers(ctx)["warnlimit"], FakeClient(), message)

    assert str(moderation.DEFAULT_WARN_LIMIT) in message.replies[0]
    assert moderation.DEFAULT_WARN_ACTION in message.replies[0]


def test_warnlimit_sets_a_threshold_and_an_action(ctx):
    message = FakeMessage("/warnlimit 4 ban")

    run(handlers(ctx)["warnlimit"], FakeClient(), message)

    assert moderation.warn_policy(ctx.chats, CHAT) == (4, "ban")
    assert "4" in message.replies[0]


def test_warnlimit_off_disables_escalation(ctx):
    message = FakeMessage("/warnlimit off")

    run(handlers(ctx)["warnlimit"], FakeClient(), message)

    assert moderation.warn_policy(ctx.chats, CHAT) == (0, moderation.DEFAULT_WARN_ACTION)
    assert "do not escalate" in message.replies[0]


def test_warnlimit_rejects_an_unknown_action(ctx):
    message = FakeMessage("/warnlimit 3 explode")

    run(handlers(ctx)["warnlimit"], FakeClient(), message)

    assert "Unknown action" in message.replies[0]
    assert moderation.warn_policy(ctx.chats, CHAT) == (
        moderation.DEFAULT_WARN_LIMIT,
        moderation.DEFAULT_WARN_ACTION,
    )


# --- /resetwarns -----------------------------------------------------------


def test_resetwarns_clears_every_warning(ctx):
    for index in range(3):
        ctx.chats.add_warning(CHAT, 22, moderator_id=11, reason=f"r{index}")
    message = FakeMessage("/resetwarns", reply=True)

    run(handlers(ctx)["resetwarns"], FakeClient(), message)

    assert ctx.chats.active_warning_count(CHAT, 22) == 0
    assert "Cleared: 3" in message.replies[0]


def test_resetwarns_says_so_when_there_was_nothing_to_clear(ctx):
    message = FakeMessage("/resetwarns", reply=True)

    run(handlers(ctx)["resetwarns"], FakeClient(), message)

    assert "no active warnings" in message.replies[0]


def test_resetwarns_refuses_to_touch_an_administrator(ctx):
    ctx.chats.add_warning(CHAT, 22, moderator_id=11, reason="x")
    message = FakeMessage("/resetwarns", reply=True)

    run(handlers(ctx)["resetwarns"], FakeClient(target=ADMIN), message)

    assert "I cannot act on an administrator" in message.replies[0]
    assert ctx.chats.active_warning_count(CHAT, 22) == 1


# --- /lockdown -------------------------------------------------------------


def test_lockdown_locks_the_group_and_records_it(ctx):
    client = FakeClient()
    message = FakeMessage("/lockdown")

    run(handlers(ctx)["lockdown"], client, message)

    kind, permissions = client.calls[0]
    assert kind == "permissions"
    assert permissions.can_send_messages is False
    assert ctx.chats.get(CHAT, "lockdown") is True
    assert "Lockdown is on" in message.replies[0]


def test_lockdown_off_restores_sending(ctx):
    ctx.chats.put(CHAT, "lockdown", True)
    ctx.chats.put(CHAT, "lockdown_permissions", {"can_send_messages": True, "can_send_photos": False})
    client = FakeClient()
    message = FakeMessage("/lockdown off")

    run(handlers(ctx)["lockdown"], client, message)

    _, permissions = client.calls[0]
    assert permissions.can_send_messages is True
    assert ctx.chats.get(CHAT, "lockdown") is False
    assert "lifted" in message.replies[0]


def test_lockdown_reports_a_permission_failure(ctx):
    class Refusing(FakeClient):
        async def set_chat_permissions(self, chat_id, permissions):
            raise RuntimeError("CHAT_ADMIN_REQUIRED")

    message = FakeMessage("/lockdown")

    run(handlers(ctx)["lockdown"], Refusing(), message)

    assert "Could not change group permissions" in message.replies[0]
    assert ctx.chats.get(CHAT, "lockdown") is None


# --- enforcement: the threshold actually acts -----------------------------


def test_warn_escalates_at_the_configured_threshold(ctx):
    client = FakeClient()
    warn = moderation.build(ctx)[1]["warn"]

    replies = []
    for _ in range(moderation.DEFAULT_WARN_LIMIT):
        message = FakeMessage("/warn 22 spam")
        run(warn, client, message)
        replies.append(message.replies[0])

    assert "Threshold reached" in replies[-1]
    assert any(call[0] == "restrict" for call in client.calls)
    assert ctx.chats.active_warning_count(CHAT, 22) == moderation.DEFAULT_WARN_LIMIT


def test_warn_does_not_escalate_before_the_threshold(ctx):
    client = FakeClient()
    warn = moderation.build(ctx)[1]["warn"]

    message = FakeMessage("/warn 22 spam")
    run(warn, client, message)

    assert "Threshold" not in message.replies[0]
    assert client.calls == []


def test_warnlimit_zero_disables_escalation(ctx):
    ctx.chats.put(CHAT, "warn_limit", 0)
    client = FakeClient()
    warn = moderation.build(ctx)[1]["warn"]

    for _ in range(5):
        run(warn, client, FakeMessage("/warn 22 spam"))

    assert client.calls == []
    assert ctx.chats.active_warning_count(CHAT, 22) == 5


def test_a_failed_escalation_is_reported_not_hidden(ctx):
    class Refusing(FakeClient):
        async def restrict_chat_member(self, *args, **kwargs):
            raise RuntimeError("CHAT_ADMIN_REQUIRED")

    ctx.chats.put(CHAT, "warn_limit", 1)
    message = FakeMessage("/warn 22 spam")

    run(moderation.build(ctx)[1]["warn"], Refusing(), message)

    assert "Escalation failed" in message.replies[0]


def test_settings_read_the_log_channel_the_runtime_is_using(ctx):
    """/setlog switches the logbook at runtime, so the panel must not show ENV."""
    ctx.logbook = SimpleNamespace(channel_id=-100999)
    message = FakeMessage("/settings")

    run(handlers(ctx)["settings"], FakeClient(), message)

    assert "-100999" in pre(message.replies[0])


def test_lockdown_restores_restricted_baseline_instead_of_opening_everything(ctx):
    client = FakeClient()
    commands = handlers(ctx)
    run(commands['lockdown'], client, FakeMessage('/lockdown'))
    run(commands['lockdown'], client, FakeMessage('/lockdown off'))
    restored = client.calls[-1][1]
    assert restored.can_send_messages is True
    assert restored.can_send_photos is False
    assert restored.can_invite_users is False
    assert restored.can_pin_messages is False


def test_repeated_lockdown_does_not_overwrite_baseline(ctx):
    client = FakeClient()
    commands = handlers(ctx)
    run(commands['lockdown'], client, FakeMessage('/lockdown'))
    original = dict(ctx.chats.get(CHAT, 'lockdown_permissions'))
    run(commands['lockdown'], client, FakeMessage('/lockdown'))
    assert len(client.calls) == 1
    assert ctx.chats.get(CHAT, 'lockdown_permissions') == original


def test_legacy_lockdown_without_baseline_refuses_unsafe_unlock(ctx):
    ctx.chats.put(CHAT, 'lockdown', True)
    client = FakeClient()
    message = FakeMessage('/lockdown off')
    run(handlers(ctx)['lockdown'], client, message)
    assert not client.calls
    assert ctx.chats.get(CHAT, 'lockdown') is True
    assert 'No saved' in message.replies[0]


def test_unlock_without_lockdown_is_noop(ctx):
    client = FakeClient()
    run(handlers(ctx)['lockdown'], client, FakeMessage('/lockdown off'))
    assert not client.calls


def test_lockdown_refuses_when_current_permissions_are_unavailable(ctx):
    class Unavailable(FakeClient):
        async def get_chat(self, chat_id):
            return SimpleNamespace(permissions=None)
    client = Unavailable()
    run(handlers(ctx)['lockdown'], client, FakeMessage('/lockdown'))
    assert not client.calls
    assert not ctx.chats.get(CHAT, 'lockdown')


def test_failed_unlock_keeps_baseline_for_retry(ctx):
    class Refusing(FakeClient):
        async def set_chat_permissions(self, *args):
            raise RuntimeError('missing rights')
    saved = {'can_send_messages': True, 'can_invite_users': False}
    ctx.chats.put(CHAT, 'lockdown', True)
    ctx.chats.put(CHAT, 'lockdown_permissions', saved)
    run(handlers(ctx)['lockdown'], Refusing(), FakeMessage('/lockdown off'))
    assert ctx.chats.get(CHAT, 'lockdown') is True
    assert ctx.chats.get(CHAT, 'lockdown_permissions') == saved


def test_lockdown_typo_does_not_lock_group(ctx):
    client = FakeClient()
    run(handlers(ctx)['lockdown'], client, FakeMessage('/lockdown of'))
    assert not client.calls
