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

    async def send_hero(self, chat_id, screen, photo):
        return await self.send(chat_id, screen)

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
    assert "<b>Jobs running</b>: 0" in body or "<td>0</td>" in body


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


class KeyboardMessage(FakeMessage):
    """Keeps the markup, so a test can see the way out of a panel."""

    def __init__(self, text="", *, uid=11):
        super().__init__(text, uid=uid)
        self.markups = []

    async def reply(self, text, **kwargs):
        self.markups.append(kwargs.get("reply_markup"))
        return await super().reply(text, **kwargs)


def test_about_offers_a_way_back_to_the_menu(tmp_path):
    from agent.ui.keyboards import CB_HELP, CB_HOME

    ctx = make_ctx(tmp_path)
    message = KeyboardMessage("/about")

    run(handlers(ctx)["about"], ctx, message)

    markup = message.markups[0]
    row = [button for line in markup.inline_keyboard for button in line]
    assert [button.callback_data for button in row] == [CB_HOME, CB_HELP]
    assert "Menu" in row[0].text


def test_status_and_the_owner_panel_both_carry_it(tmp_path):
    ctx = make_ctx(tmp_path, owner_id=11)

    for name in ("status", "owner"):
        message = KeyboardMessage(f"/{name}")
        run(handlers(ctx)[name], ctx, message)
        assert message.markups[-1] is not None, name


def test_uptime_uses_process_clock_and_real_probe_counts(tmp_path):
    ctx = make_ctx(tmp_path)
    now = [100.0]
    ctx.monitor = HealthMonitor(clock=lambda: now[0])
    ctx.monitor.record_success()
    now[0] += 3605
    ctx.monitor.record_failure('test failure')
    message = FakeMessage('/uptime')
    run(handlers(ctx)['uptime'], ctx, message)
    body = message.replies[0]
    assert '1h 0m 5s' in body
    assert '3605s ago' in body
    assert 'Successful probes' in body and 'Failed probes' in body
    assert 'Not a 24/7 availability percentage' in body


def test_uptime_without_monitor_does_not_fabricate_measurements(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.monitor = None
    message = FakeMessage('/uptime')
    run(handlers(ctx)['uptime'], ctx, message)
    assert 'unavailable' in message.replies[0]


def test_jobs_private_owner_isolation_and_sensitive_details_hidden(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        async def run(job):
            return '/tmp/private'
        own = ctx.jobs.submit('leech', 11, run, label='https://secret.example/token')
        foreign = ctx.jobs.submit('encoder', 22, run)
        await asyncio.gather(own.task, foreign.task)
        own.error = 'raw credential'
        own.detail = '/tmp/sensitive'
        handler = core.build(ctx)[1]['jobs']
        group = FakeMessage('/jobs')
        await handler(None, group)
        assert 'privately' in group.replies[-1]
        message = FakeMessage('/jobs'); message.chat.id = 11
        await handler(None, message)
        text = message.replies[-1]
        assert own.id in text and foreign.id not in text
        assert 'done' in text
        for secret in ('secret.example', 'raw credential', '/tmp/sensitive', '/tmp/private'):
            assert secret not in text
    asyncio.run(scenario())


def test_cancel_by_id_is_selective_owner_bound_and_honest(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        blocker = asyncio.Event()
        async def waiting(job):
            await blocker.wait()
        first = ctx.jobs.submit('leech', 11, waiting)
        second = ctx.jobs.submit('encoder', 11, waiting)
        foreign = ctx.jobs.submit('leech', 22, waiting)
        command = handlers(ctx)['cancel']
        try:
            await asyncio.sleep(0)
            msg = FakeMessage('/cancel ' + first.id)
            await command(None, msg)
            assert first.state is JobState.CANCELLED
            assert not second.finished and not foreign.finished
            assert 'other jobs are unchanged' in msg.replies[-1]
            for job_id in (foreign.id, 'missing-id'):
                request = FakeMessage('/cancel ' + job_id)
                await command(None, request)
                assert 'No matching job belongs to you' in request.replies[-1]
            done = FakeMessage('/cancel ' + first.id)
            await command(None, done)
            assert 'already finished' in done.replies[-1]
            malformed = FakeMessage('/cancel one two')
            await command(None, malformed)
            assert 'Use /cancel' in malformed.replies[-1]
        finally:
            await ctx.jobs.shutdown()
    asyncio.run(scenario())


def test_jobs_module_filter_keeps_owner_boundary_and_rejects_extra_args(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        async def done(job):
            pass
        encoder = ctx.jobs.submit('encoder', 11, done)
        leech = ctx.jobs.submit('leech', 11, done)
        foreign = ctx.jobs.submit('encoder', 22, done)
        await asyncio.gather(encoder.task, leech.task, foreign.task)
        command = handlers(ctx)['jobs']
        msg = FakeMessage('/jobs encoder'); msg.chat.id = 11
        await command(None, msg)
        assert encoder.id in msg.replies[-1]
        assert leech.id not in msg.replies[-1] and foreign.id not in msg.replies[-1]
        for text in ('/jobs encoder extra', '/jobs <bad>', '/jobs ' + 'a'*33):
            invalid = FakeMessage(text); invalid.chat.id = 11
            await command(None, invalid)
            assert 'Use /jobs' in invalid.replies[-1]
        empty = FakeMessage('/jobs absent'); empty.chat.id = 11
        await command(None, empty)
        assert 'No matching jobs' in empty.replies[-1]
    asyncio.run(scenario())


def test_status_reports_native_capabilities_without_network_lookup(tmp_path):
    from unittest.mock import AsyncMock
    ctx = make_ctx(tmp_path)
    client = SimpleNamespace(me=SimpleNamespace(
        supports_guest_queries=True, can_manage_bots=False, supports_join_request_queries=None,
    ), get_me=AsyncMock())
    message = FakeMessage('/status')
    run(handlers(ctx)['status'], ctx, message, client=client)
    body = str(message.replies[0])
    assert 'Telegram guest chat' in body and 'Reported enabled' in body
    assert 'Telegram bot management' in body and 'Reported disabled' in body
    assert 'Telegram Guard' in body and 'Not reported' in body
    assert 'not a live' in body
    client.get_me.assert_not_awaited()


def test_status_unknown_identity_does_not_claim_modes_are_disabled(tmp_path):
    ctx = make_ctx(tmp_path)
    message = FakeMessage('/status')
    run(handlers(ctx)['status'], ctx, message)
    body = str(message.replies[0])
    assert body.count('Not reported') == 3
    assert 'Reported disabled' not in body


def test_status_uses_attached_identity_and_requires_boolean_capability_flags(tmp_path):
    ctx = make_ctx(tmp_path)
    for value in (True, False, 1, 0, 'true', None):
        ctx.client = SimpleNamespace(me=SimpleNamespace(
            supports_guest_queries=value, can_manage_bots=value, supports_join_request_queries=value,
        ))
        message = FakeMessage('/status')
        run(handlers(ctx)['status'], ctx, message)
        body = str(message.replies[0])
        expected = 'Reported enabled' if value is True else 'Reported disabled' if value is False else 'Not reported'
        assert body.count(expected) == 3
