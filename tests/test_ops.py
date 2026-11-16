"""Operations: instance lease, plugin runtime, watchdog sweeps, restart, events."""

import asyncio
import os
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest

from agent.config import Settings
from agent.modules import ops
from agent.platform.chats import ChatStore
from agent.platform.context import ModuleContext
from agent.platform.events import EventLog
from agent.platform.instance import InstanceLease
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.manifest import PluginManifest, PluginRegistry
from agent.platform.runtime import PluginRuntime
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
        self.from_user = SimpleNamespace(id=uid, first_name="Owner")
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


class FakeClient:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_handler(self, handler, group=0):
        self.added.append((handler, group))

    def remove_handler(self, handler, group=0):
        self.removed.append((handler, group))


# --- instance lease --------------------------------------------------------


def test_only_one_instance_holds_the_lease(tmp_path):
    first = InstanceLease(tmp_path / "lock", owner="first")
    second = InstanceLease(tmp_path / "lock", owner="second")

    assert first.try_acquire() is True
    assert second.try_acquire() is False
    assert second.other == "first"


def test_an_expired_lease_can_be_taken(tmp_path):
    lease = InstanceLease(tmp_path / "lock", owner="ghost", ttl=-5)
    lease.try_acquire()

    newcomer = InstanceLease(tmp_path / "lock", owner="newcomer")

    assert newcomer.try_acquire() is True


def test_release_frees_the_lease_for_the_next_process(tmp_path):
    first = InstanceLease(tmp_path / "lock", owner="first")
    first.try_acquire()
    first.release()

    assert InstanceLease(tmp_path / "lock", owner="second").try_acquire() is True


def test_heartbeat_notices_a_takeover(tmp_path):
    first = InstanceLease(tmp_path / "lock", owner="first")
    first.try_acquire()
    # Simulate the lease being stolen (e.g. this copy was frozen past the TTL).
    InstanceLease(tmp_path / "lock", owner="thief").path.write_text(
        '{"owner": "thief", "until": 9999999999}'
    )

    assert first.heartbeat() is False
    assert first.held is False


def test_acquire_waits_then_takes_over(tmp_path):
    holder = InstanceLease(tmp_path / "lock", owner="holder")
    holder.try_acquire()
    waiter = InstanceLease(tmp_path / "lock", owner="waiter")

    async def scenario():
        async def free_soon():
            await asyncio.sleep(0.05)
            holder.release()

        task = asyncio.create_task(free_soon())
        acquired = await waiter.acquire(wait_seconds=5, poll=0.02)
        await task
        return acquired

    assert asyncio.run(scenario()) is True


def test_acquire_gives_up_rather_than_double_serving(tmp_path):
    holder = InstanceLease(tmp_path / "lock", owner="holder")
    holder.try_acquire()
    waiter = InstanceLease(tmp_path / "lock", owner="waiter")

    assert asyncio.run(waiter.acquire(wait_seconds=0.1, poll=0.02)) is False


# --- plugin runtime --------------------------------------------------------


def make_runtime(tmp_path):
    registry = PluginRegistry()
    runtime = PluginRuntime(registry, state_path=tmp_path / "plugins.json")
    for slug, commands in (("ops", ("restart",)), ("demo", ("demo",))):
        registry.register(
            PluginManifest(slug=slug, name=slug, version="1", description=""),
            {c: (lambda *_: None) for c in commands},
        )
    client = FakeClient()
    runtime.attach(client)
    handler = object()
    runtime.track("demo", handler, 0)
    client.add_handler(handler, 0)
    return registry, runtime, client, handler


def test_disabling_a_plugin_detaches_its_handlers(tmp_path):
    registry, runtime, client, handler = make_runtime(tmp_path)

    assert runtime.disable("demo") is True

    assert (handler, 0) in client.removed
    assert registry.is_enabled("demo") is False


def test_a_disabled_plugin_stays_disabled_after_a_restart(tmp_path):
    registry, runtime, _client, _handler = make_runtime(tmp_path)
    runtime.disable("demo")

    reloaded = PluginRuntime(registry, state_path=tmp_path / "plugins.json")

    assert reloaded.wants_disabled("demo") is True


def test_enabling_reattaches_handlers(tmp_path):
    registry, runtime, client, handler = make_runtime(tmp_path)
    runtime.disable("demo")

    assert runtime.enable("demo") is True

    assert (handler, 0) in client.added
    assert registry.is_enabled("demo") is True


def test_ops_cannot_disable_itself(tmp_path):
    _registry, runtime, _client, _handler = make_runtime(tmp_path)

    with pytest.raises(ValueError):
        runtime.disable("ops")


# --- the ops commands ------------------------------------------------------


@pytest.fixture()
def ctx(tmp_path):
    settings = Settings.from_env({**ENV, "OWNER_ID": "11"})
    ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        chats=ChatStore(tmp_path),
        events=EventLog(),
        lease=InstanceLease(tmp_path / "lock", owner="test"),
    )
    registry = PluginRegistry()
    runtime = PluginRuntime(registry, state_path=tmp_path / "plugins.json")
    for slug, commands in (("ops", ops.MANIFEST.commands), ("demo", ("demo",))):
        registry.register(
            PluginManifest(slug=slug, name=slug, version="1", description=""),
            {c: (lambda *_: None) for c in commands},
        )
    runtime.track("demo", object(), 0)
    ctx.registry = registry
    ctx.runtime = runtime
    ctx.lease.try_acquire()
    return ctx


def run(handler, message, client=None):
    return asyncio.run(handler(client, message))


def handlers(ctx):
    return ops.build(ctx)[1]


def test_restart_is_owner_only(ctx):
    message = FakeMessage("/restart", uid=999)

    run(handlers(ctx)["restart"], message)

    assert message.replies == [ops.OWNER_ONLY]


def test_restart_refuses_while_jobs_run(ctx):
    started = asyncio.Event()

    async def scenario():
        async def runner(job):
            started.set()
            await asyncio.sleep(30)

        job = ctx.jobs.submit("demo", 11, runner, label="busy")
        await asyncio.wait_for(started.wait(), timeout=5)
        message = FakeMessage("/restart")
        await handlers(ctx)["restart"](None, message)
        job.task.cancel()
        with suppress(asyncio.CancelledError):
            await job.task
        return message

    message = asyncio.run(scenario())
    assert "still running" in message.replies[0]


def test_restart_force_stops_the_process(ctx):
    called = []
    ctx.runtime.restart_hook = lambda: called.append(True)
    message = FakeMessage("/restart force")

    run(handlers(ctx)["restart"], message)

    assert called == [True]
    assert "Restarting now" in message.replies[0]
    assert ctx.runtime.restart_requested is True


def test_watchdog_reports_the_lease(ctx):
    message = FakeMessage("/watchdog")

    run(handlers(ctx)["watchdog"], message)

    body = message.replies[0]
    assert "held by this process" in body
    assert "Jobs running" in body


def test_sweep_removes_only_stale_working_directories(tmp_path):
    stale = tmp_path / "enc-old"
    stale.mkdir()
    (stale / "out.mp4").write_bytes(b"x" * 100)
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = tmp_path / "enc-fresh"
    fresh.mkdir()

    removed, freed = ops.sweep_temp_dirs(root=tmp_path)

    assert (removed, freed) == (1, 100)
    assert not stale.exists()
    assert fresh.exists()


def test_watchdog_run_purges_expired_links(ctx):
    ctx.links.create("file-1", 11, ttl_hours=0)
    message = FakeMessage("/watchdog run")

    run(handlers(ctx)["watchdog"], message)

    assert "Expired links purged: 1" in message.replies[0]


def test_plugins_lists_state(ctx):
    message = FakeMessage("/plugins")

    run(handlers(ctx)["plugins"], message)

    body = message.replies[0]
    assert "demo" in body
    assert "plugin:ops" not in str(message.replies)


def test_plugin_off_and_on(ctx):
    off = FakeMessage("/plugin demo off")
    run(handlers(ctx)["plugin"], off)
    assert "now disabled" in off.replies[0]
    assert ctx.registry.is_enabled("demo") is False

    on = FakeMessage("/plugin demo on")
    run(handlers(ctx)["plugin"], on)
    assert "now enabled" in on.replies[0]
    assert ctx.registry.is_enabled("demo") is True


def test_plugin_unknown_slug_is_reported(ctx):
    message = FakeMessage("/plugin nope off")

    run(handlers(ctx)["plugin"], message)

    assert "No plugin named" in message.replies[0]


def test_events_lists_recent_activity(ctx):
    ctx.events.emit("command", name="start", uid=11)
    message = FakeMessage("/events")

    run(handlers(ctx)["events"], message)

    assert "command" in message.replies[0]
    assert "recorded" in message.replies[0]


def test_runtime_on_off_is_idempotent_and_does_not_duplicate_handlers(tmp_path):
    registry, runtime, client, handler = make_runtime(tmp_path)
    initial = len(client.added)
    assert runtime.enable('demo') is False
    assert len(client.added) == initial
    assert runtime.disable('demo') is True
    removed = len(client.removed)
    assert runtime.disable('demo') is False
    assert len(client.removed) == removed
    assert runtime.enable('demo') is True
    added = len(client.added)
    assert runtime.enable('demo') is False
    assert len(client.added) == added


@pytest.mark.parametrize('action', ['enable', 'disable'])
def test_runtime_save_failure_keeps_registry_and_handlers_unchanged(tmp_path, monkeypatch, action):
    registry, runtime, client, _ = make_runtime(tmp_path)
    if action == 'enable':
        runtime.disable('demo')
    previous = set(runtime._disabled)
    enabled = registry.is_enabled('demo')
    added, removed = list(client.added), list(client.removed)
    def fail():
        raise RuntimeError('storage unavailable')
    monkeypatch.setattr(runtime, '_save', fail)
    with pytest.raises(RuntimeError, match='storage unavailable'):
        getattr(runtime, action)('demo')
    assert registry.is_enabled('demo') == enabled
    assert runtime._disabled == previous
    assert client.added == added and client.removed == removed


@pytest.mark.parametrize('action', ['enable', 'disable'])
def test_partial_handler_failure_compensates_completed_work_and_settings(tmp_path, action):
    registry, runtime, _, first = make_runtime(tmp_path)
    second = object()
    runtime.track('demo', second, 2)
    if action == 'enable':
        runtime.disable('demo')
    prior_enabled = registry.is_enabled('demo')
    prior_disabled = set(runtime._disabled)
    calls = []
    class PartialClient:
        def add_handler(self, handler, group):
            calls.append(('add', handler, group))
            if action == 'enable' and handler is second:
                raise RuntimeError('injected failure')
        def remove_handler(self, handler, group):
            calls.append(('remove', handler, group))
            if action == 'disable' and handler is second:
                raise RuntimeError('injected failure')
    runtime.attach(PartialClient())
    notices = []
    runtime.change_hook = lambda: notices.append('changed')
    with pytest.raises(RuntimeError, match='no success confirmed'):
        getattr(runtime, action)('demo')
    assert registry.is_enabled('demo') == prior_enabled
    assert runtime._disabled == prior_disabled
    assert notices == []
    assert calls[-1] == ('remove' if action == 'enable' else 'add', first, 0)
    reloaded = PluginRuntime(registry, state_path=runtime.state_path)
    assert reloaded._disabled == prior_disabled


def test_failed_handler_compensation_is_logged_without_claiming_success(tmp_path, caplog):
    registry, runtime, _, _ = make_runtime(tmp_path)
    runtime.disable('demo')
    runtime.track('demo', object(), 2)
    class BrokenClient:
        calls = 0
        def add_handler(self, *args):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('add failed')
        def remove_handler(self, *args):
            raise RuntimeError('rollback failed')
    runtime.attach(BrokenClient())
    with pytest.raises(RuntimeError, match='no success confirmed'):
        runtime.enable('demo')
    assert not registry.is_enabled('demo')
    assert '#Errors' in caplog.text and 'reconciliation needed' in caplog.text
