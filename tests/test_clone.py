"""Clones: a second bot token, its own process-shaped world, one panel.

The tests never touch Telegram: the bot factory is injected, so what is being
checked is the decision logic — who may clone, how many, what a press does, and
what happens to a clone whose token Telegram refuses.
"""

import asyncio
import json
import os
from types import SimpleNamespace

from pyrogram.enums import ButtonStyle

from agent.config import Settings
from agent.modules import clone as clone_module
from agent.modules.clone.store import Clone, CloneStore, parse_token
from agent.platform.actions import ActionRouter
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.storage import Storage
from agent.ui.theme import Theme

import pytest


@pytest.fixture(autouse=True)
def _fresh_factory_log():
    FakeBot.made.clear()
    yield
    FakeBot.made.clear()

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
    "OWNER_ID": "11",
    "TOKEN_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
}
OWNER = 11
MEMBER = 22
TOKEN_A = "111111111:AAHfakeTokenValueForTests_aaaaaaaa"
TOKEN_B = "222222222:AAHfakeTokenValueForTests_bbbbbbbb"


class FakeClient:
    def __init__(self, username, *, fails=False):
        self.username = username
        self.fails = fails
        self.started = False
        self.stopped = False

    async def start(self):
        if self.fails:
            raise RuntimeError("bot token is invalid")
        self.started = True
        return self

    async def stop(self):
        self.stopped = True

    async def get_me(self):
        return SimpleNamespace(username=self.username, id=int(self.username.strip("bot")))


class FakeBot:
    """Stands in for AgentBot: build() returns a ready client."""

    made = []

    def __init__(self, settings, *, fails=False):
        self.settings = settings
        self.fails = fails
        self.client = FakeClient(f"bot{settings.bot_token.split(':')[0]}", fails=fails)
        FakeBot.made.append(self)

    def build(self):
        return self.client


def factory(settings):
    return FakeBot(settings)


class FakePremium:
    def __init__(self, premium_ids=()):
        self.ids = set(premium_ids)

    def is_premium(self, user_id):
        return int(user_id) in self.ids

    def tier(self, user_id):
        return SimpleNamespace(label="premium" if self.is_premium(user_id) else "free")


class FakeMessage:
    def __init__(self, text, *, uid=MEMBER):
        self.text = text
        self.chat = SimpleNamespace(id=uid)
        self.from_user = SimpleNamespace(id=uid, first_name="Ada")
        self.replies = []
        self.markups = []

    async def reply(self, text, **kwargs):
        self.replies.append(str(text))
        self.markups.append(kwargs.get("reply_markup"))
        return SimpleNamespace(id=1)


class FakeQuery:
    def __init__(self, data, *, uid=MEMBER):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.answers = []
        self.edits = []
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=7),
            id=9,
            edit_text=self._edit,
        )

    async def _edit(self, text=None, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def make_ctx(tmp_path, *, premium=None, clone_limit=5):
    settings = Settings.from_env(
        {**ENV, "DATA_DIR": str(tmp_path / "data"), "CLONE_LIMIT": str(clone_limit)}
    )
    ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        monitor=None,
    )
    ctx.actions = ActionRouter()
    ctx.premium = premium if premium is not None else FakePremium({MEMBER})
    ctx.clone_factory = factory
    return ctx


def build(tmp_path, **kwargs):
    ctx = make_ctx(tmp_path, **kwargs)
    manifest, handlers = clone_module.build(ctx)
    return ctx, manifest, handlers


def run(handler, ctx, message):
    return asyncio.run(handler(None, message))


def buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def press(ctx, data, *, uid=MEMBER):
    query = FakeQuery(f"clone:{data}", uid=uid)
    asyncio.run(ctx.actions.dispatch(None, query))
    return query


# --- tokens ---------------------------------------------------------------


def test_a_token_is_checked_for_shape_before_telegram_is_asked():
    ok, _reason, bot_id = parse_token(TOKEN_A)
    assert ok and bot_id == 111111111

    bad_ok, reason, _bot_id = parse_token("not-a-token")
    assert bad_ok is False and "123456789:AA" in reason


# --- cloning --------------------------------------------------------------


def test_a_member_can_clone_once_and_the_clone_runs(tmp_path):
    ctx, manifest, handlers = build(tmp_path)
    message = FakeMessage(f"/clone {TOKEN_A}")

    run(handlers["clone"], ctx, message)

    assert "Clone started" in message.replies[0]
    record = ctx.clones.current()[0]
    assert record.bot_id == 111111111 and record.owner_id == MEMBER
    assert ctx.clones.is_running(111111111)
    # The token sender owns this clone, not the parent deployment.
    clone_settings = FakeBot.made[0].settings
    assert clone_settings.owner_id == MEMBER
    assert str(clone_settings.data_dir).endswith("clones/111111111")
    assert clone_settings.session_name == "agent_clone_111111111"


def test_free_members_cannot_clone_and_premium_allows_three(tmp_path):
    ctx, _, commands = build(tmp_path, premium=FakePremium())
    denied = FakeMessage(f"/clone {TOKEN_A}")
    run(commands["clone"], ctx, denied)
    assert "requires bot premium" in denied.replies[0]
    assert not ctx.clones.current()
    rich_ctx, _, rich_commands = build(tmp_path / "rich", premium=FakePremium({MEMBER}))
    for token in (TOKEN_A, TOKEN_B, "333333333:AAHfakeTokenValueForTests_cccccccc"):
        message = FakeMessage(f"/clone {token}")
        run(rich_commands["clone"], rich_ctx, message)
        assert "Clone started" in message.replies[0]


def test_the_deployment_ceiling_is_final(tmp_path):
    ctx, _manifest, handlers = build(tmp_path, clone_limit=1, premium=FakePremium({MEMBER}))
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    second = FakeMessage(f"/clone {TOKEN_B}")
    run(handlers["clone"], ctx, second)

    assert "deployment is full" in second.replies[0]


def test_a_token_telegram_refuses_leaves_no_record(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)

    class BrokenBot(FakeBot):
        def __init__(self, settings):
            super().__init__(settings, fails=True)

    ctx.clone_factory = lambda settings: BrokenBot(settings)
    _manifest, handlers = clone_module.build(ctx)
    message = FakeMessage(f"/clone {TOKEN_A}")

    run(handlers["clone"], ctx, message)

    assert "Could not start that clone" in message.replies[0]
    assert ctx.clones.current() == ()


# --- the panel ------------------------------------------------------------


def test_mybots_lists_the_clones_with_start_stop_and_delete(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    message = FakeMessage("/mybots")

    run(handlers["mybots"], ctx, message)

    row = buttons(message.markups[0])
    assert [b.callback_data for b in row[:3]] == [
        "clone:111111111:stop",
        "clone:111111111:profile",
        "clone:111111111:delete",
    ]
    assert row[2].style is ButtonStyle.DANGER
    assert "Profile" in message.replies[0]


def test_an_owner_press_stops_and_restarts_the_clone(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))

    stopped = press(ctx, "111111111:stop")
    assert ctx.clones.is_running(111111111) is False
    assert "is stopped" in stopped.answers[-1][0]
    assert ctx.clones.current()[0].disabled is True

    started = press(ctx, "111111111:start")
    assert ctx.clones.is_running(111111111) is True
    assert "is running" in started.answers[-1][0]


def test_a_stranger_cannot_press_somebody_elses_clone(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))

    refused = press(ctx, "111111111:delete", uid=OWNER + 500)

    assert ctx.clones.is_running(111111111) is True
    assert len(ctx.clones.current()) == 1
    text, alert = refused.answers[-1]
    assert alert is True and "Only its owner" in text


def test_delclone_stops_the_client_and_removes_the_record(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    client = FakeBot.made[0].client
    message = FakeMessage("/delclone 111111111")

    run(handlers["delclone"], ctx, message)

    assert "Deleted the clone" in message.replies[0]
    assert client.stopped is True
    assert ctx.clones.current() == ()


def test_restore_starts_every_clone_that_was_running(tmp_path):
    ctx, _manifest, handlers = build(tmp_path, premium=FakePremium({MEMBER}))
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_B}"))
    asyncio.run(ctx.clones.stop_all())
    assert ctx.clones.running() == ()

    started = asyncio.run(ctx.clones.restore())

    assert len(started) == 2
    assert len(ctx.clones.running()) == 2


def test_clonestats_is_owner_only(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))

    member = FakeMessage("/clonestats", uid=MEMBER)
    run(handlers["clonestats"], ctx, member)
    assert "reserved for the bot owner" in member.replies[0]

    owner = FakeMessage("/clonestats", uid=OWNER)
    run(handlers["clonestats"], ctx, owner)
    assert "Clone statistics" in owner.replies[0]


# --- the store ------------------------------------------------------------


def test_the_store_keeps_tokens_out_of_sight_and_off_other_accounts(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    path = tmp_path / "data" / "clones.json"

    payload = json.loads(path.read_text(encoding="utf-8"))
    from agent.platform.secrets import box_from
    assert "token" not in payload[0]
    assert box_from(ctx.settings).decrypt(payload[0]["token_enc"]) == TOKEN_A
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600

    message = FakeMessage("/mybots", uid=MEMBER)
    run(handlers["mybots"], ctx, message)
    assert TOKEN_A not in message.replies[0]


def test_a_record_survives_a_reload(tmp_path):
    store = CloneStore(tmp_path)
    store.add(Clone(bot_id=1, owner_id=2, token=TOKEN_A, username="demo"))

    again = CloneStore(tmp_path)
    assert again.get(1).username == "demo"
    assert again.by_owner(2)[0].bot_id == 1
    assert again.remove(1) is True
    assert CloneStore(tmp_path).count() == 0


# --- profiles --------------------------------------------------------------


def test_the_default_profile_runs_the_deployments_plugins(tmp_path):
    from agent.modules.clone import profiles

    settings = Settings.from_env(ENV)

    assert profiles.clean(None) == profiles.STANDARD
    assert profiles.plugins_for(profiles.STANDARD, settings) == tuple(slug for slug in settings.plugins if slug != "clone")


def test_a_restricted_profile_never_gets_ops_or_clone():
    from agent.modules.clone import profiles

    for name in (profiles.FILES, profiles.TINY):
        plugins = set(profiles.plugins_for(name, Settings.from_env(ENV)))
        assert not (plugins & {"ops", "clone"}), name


def test_the_files_profile_is_the_file_machinery(tmp_path):
    from agent.modules.clone import profiles

    plugins = set(profiles.plugins_for("files", Settings.from_env(ENV)))

    assert {"filestore", "leech", "linkshare", "renamer"} <= plugins
    assert not plugins & {"moderation", "music", "premium"}


def test_a_clone_starts_with_the_plugins_its_profile_names(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A} files"))

    settings = FakeBot.made[0].settings

    assert settings.plugins == ("filestore", "leech", "linkshare", "renamer", "postmaker")
    assert settings.db_scope == "clone:111111111"


def test_an_unknown_profile_is_refused_and_nothing_is_created(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    message = FakeMessage(f"/clone {TOKEN_A} turbo")

    run(handlers["clone"], ctx, message)

    assert "Unknown profile" in message.replies[0]
    assert ctx.clones.current() == ()


def test_the_panel_shows_the_profile_and_offers_one(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A} files"))
    message = FakeMessage("/mybots")

    run(handlers["mybots"], ctx, message)

    assert "files" in message.replies[0]
    assert "clone:111111111:profile" in [b.callback_data for b in buttons(message.markups[0])]


def test_choosing_a_profile_restarts_the_clone_with_it(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))
    FakeBot.made.clear()

    query = press(ctx, "111111111:p:tiny")

    assert "restarted on tiny" in query.answers[0][0]
    assert ctx.clones.record(111111111).profile == "tiny"
    assert FakeBot.made[-1].settings.plugins == ()
    assert ctx.clones.profile(111111111) == "tiny"


def test_the_profile_picker_lists_every_profile(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))

    query = press(ctx, "111111111:profile")

    data = [button.callback_data for button in buttons(query.edits[0][1])]
    assert "clone:111111111:p:files" in data
    assert "clone:111111111:p:tiny" in data
    assert "clone:111111111:back" in data


def test_an_unknown_profile_button_is_refused(tmp_path):
    ctx, _manifest, handlers = build(tmp_path)
    run(handlers["clone"], ctx, FakeMessage(f"/clone {TOKEN_A}"))

    query = press(ctx, "111111111:p:everything")

    assert query.answers[0][1] is True          # an alert, not a silent no-op
    assert ctx.clones.record(111111111).profile == "standard"
