"""Core-extras commands: menu, about, status, cancel, owner."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace


from agent import __version__
from agent.config import Settings
from agent.health import HealthMonitor
from agent.modules import core
from agent.modules.encoder import MANIFEST as ENCODER
from agent.modules.linkshare import MANIFEST as LINKSHARE
from agent.modules.moderation import MANIFEST as MODERATION
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue, JobState
from agent.platform.links import LinkStore
from agent.platform.manifest import PluginRegistry
from agent.platform.storage import Storage
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


class FakeMessage:
    def __init__(self, text="", *, uid=11):
        self.text = text
        self.chat = SimpleNamespace(id=7)
        self.from_user = SimpleNamespace(id=uid, first_name="Ada")
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, screen):
        self.sent.append((chat_id, screen))
        return SimpleNamespace(id=1)


def make_ctx(tmp_path, *, owner_id=None, sender=None):
    settings = Settings.from_env({**ENV, **({"OWNER_ID": str(owner_id)} if owner_id else {})})
    ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=sender or FakeSender(),
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        monitor=HealthMonitor(),
    )
    ctx.registry = PluginRegistry()
    for manifest in (core.MANIFEST, ENCODER, LINKSHARE, MODERATION):
        ctx.registry.register(manifest, {c: (lambda *_: None) for c in manifest.commands})
    return ctx


def run(handler, ctx, message, client=None):
    return asyncio.run(handler(client, message))


def handlers(ctx):
    return core.build(ctx)[1]


def test_menu_uses_the_same_screen_as_start(tmp_path):
    sender = FakeSender()
    ctx = make_ctx(tmp_path, sender=sender)

    run(handlers(ctx)["menu"], ctx, FakeMessage("/menu"))

    assert len(sender.sent) == 1
    chat_id, screen = sender.sent[0]
    assert chat_id == 7
    assert screen.rich_text


def test_about_reports_real_modules_and_counts(tmp_path):
    ctx = make_ctx(tmp_path)
    message = FakeMessage("/about")

    run(handlers(ctx)["about"], ctx, message)

    assert __version__ in message.replies[0]
    assert "Moderation" in message.replies[0]
    assert str(len(ctx.registry.active_commands())) in message.replies[0]


def test_status_reports_live_counters(tmp_path):
    ctx = make_ctx(tmp_path)
    message = FakeMessage("/status")

    run(handlers(ctx)["status"], ctx, message)

    body = message.replies[0]
    assert "Uptime" in body
    assert "Probes" in body
    # Rendered as a table row now: label and value are separate cells.
    assert "Jobs running" in body
    assert "| 0 " in body or "\u2502 0 " in body


def test_cancel_actually_cancels_the_callers_job(tmp_path):
    ctx = make_ctx(tmp_path)
    started = asyncio.Event()

    async def scenario():
        async def runner(job):
            started.set()
            await asyncio.Event().wait()  # never finishes on its own

        job = ctx.jobs.submit("encoder", 11, runner, label="slow")
        await asyncio.wait_for(started.wait(), timeout=5)
        message = FakeMessage("/cancel")
        await handlers(ctx)["cancel"](None, message)
        with suppress(asyncio.CancelledError):
            await job.task
        return job, message

    job, message = asyncio.run(scenario())

    assert job.state is JobState.CANCELLED
    assert "Cancelled 1 job(s)." in message.replies[0]


def test_cancel_says_when_nothing_is_running(tmp_path):
    ctx = make_ctx(tmp_path)
    message = FakeMessage("/cancel")

    run(handlers(ctx)["cancel"], ctx, message)

    assert "Nothing was running" in message.replies[0]


def test_cancel_leaves_other_peoples_jobs_alone(tmp_path):
    ctx = make_ctx(tmp_path)
    started = asyncio.Event()

    async def scenario():
        async def runner(job):
            started.set()
            await asyncio.sleep(30)

        job = ctx.jobs.submit("encoder", 999, runner, label="theirs")
        await asyncio.wait_for(started.wait(), timeout=5)
        await handlers(ctx)["cancel"](None, FakeMessage("/cancel", uid=11))
        state = job.state
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        return state

    # /cancel from a different user must not touch this job
    assert asyncio.run(scenario()) is JobState.RUNNING


def test_owner_without_owner_id_explains_the_setting(tmp_path):
    ctx = make_ctx(tmp_path)
    message = FakeMessage("/owner")

    run(handlers(ctx)["owner"], ctx, message)

    assert "OWNER_ID" in message.replies[0]


def test_owner_refuses_a_stranger(tmp_path):
    ctx = make_ctx(tmp_path, owner_id=555)
    message = FakeMessage("/owner", uid=11)

    run(handlers(ctx)["owner"], ctx, message)

    assert message.replies == [core.OWNER_ONLY]


def test_owner_panel_for_the_owner(tmp_path):
    ctx = make_ctx(tmp_path, owner_id=11)
    message = FakeMessage("/owner", uid=11)

    run(handlers(ctx)["owner"], ctx, message)

    body = message.replies[0]
    assert "Owner panel" in body
    assert "Uptime" in body
    assert "Commands" in body
