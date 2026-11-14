"""The worker lifecycle: real states instead of a boolean.

`is_running` cannot say *why* a clone is not up, so an owner sees "stopped" for a
revoked token, a crash and a deliberate stop alike. These tests pin the states,
the transitions between them, and what the supervisor does when a client dies.
"""

from types import SimpleNamespace

import pytest

from agent.modules.clone import lifecycle
from agent.modules.clone.lifecycle import LifecycleError, Registry, State, WorkerState
from agent.modules.clone.manager import CloneError, CloneManager
from agent.modules.clone.store import Clone, CloneStore

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}

TOKEN = "111111111:AAHfakeTokenValueForTests_1234567890abc"


# --- the state machine -----------------------------------------------------


def test_a_new_worker_is_queued_not_running():
    state = WorkerState()

    assert state.state is State.QUEUED
    assert state.live is False
    assert state.label == "⏳ Queued"


def test_the_happy_path_resets_attempts():
    state = WorkerState()
    state.move(State.VALIDATING)
    state.move(State.STARTING)
    state.move(State.FAILED, error="401 Unauthorized")
    assert state.attempts == 1 and state.last_error == "401 Unauthorized"

    state.move(State.VALIDATING)
    state.move(State.STARTING)
    state.move(State.RUNNING)

    assert state.attempts == 0
    assert state.last_error == ""
    assert state.live is True


def test_an_impossible_transition_is_refused():
    state = WorkerState()
    with pytest.raises(LifecycleError, match="queued -> running"):
        state.move(State.RUNNING)


def test_stopping_goes_through_stopping():
    state = WorkerState(state=State.RUNNING)
    state.move(State.STOPPING)
    state.move(State.STOPPED)

    assert state.state is State.STOPPED
    assert state.live is False


def test_a_degraded_worker_is_still_live():
    state = WorkerState(state=State.RUNNING)
    state.move(State.DEGRADED, error="connection lost")

    assert state.live is True
    assert state.attempts == 1
    assert state.label == "⚠️ Degraded"


def test_moving_to_the_state_it_is_already_in_is_a_no_op():
    state = WorkerState(state=State.RUNNING)
    assert state.move(State.RUNNING) is state


def test_backoff_doubles_and_is_capped():
    assert lifecycle.backoff(0) == 0.0
    assert lifecycle.backoff(1) == 15.0
    assert lifecycle.backoff(3) == 60.0
    assert lifecycle.backoff(40) == lifecycle.BACKOFF_CAP


def test_the_registry_counts_states():
    registry = Registry()
    registry.move(1, State.VALIDATING)
    registry.move(1, State.STARTING)
    registry.move(1, State.RUNNING)
    registry.move(2, State.VALIDATING)
    registry.move(2, State.FAILED, error="revoked")
    registry.get(3)  # never started

    assert registry.counts() == {State.RUNNING: 1, State.FAILED: 1, State.QUEUED: 1}
    assert registry.get(2).last_error == "revoked"


# --- the manager -----------------------------------------------------------


class FakeClient:
    def __init__(self, *, fail=False, identity=True):
        self.fail = fail
        self.identity = identity
        self.started = 0
        self.stopped = 0
        self.is_connected = True

    async def start(self):
        self.started += 1
        if self.fail:
            raise RuntimeError("401 UNAUTHORIZED")

    async def stop(self):
        self.stopped += 1

    async def get_me(self):
        if not self.identity:
            raise RuntimeError("no identity")
        return SimpleNamespace(username="helper_bot")

    async def send_document(self, **kwargs):
        return SimpleNamespace(document=SimpleNamespace(file_id="x"))


class FakeBot:
    def __init__(self, settings, *, fail=False, identity=True):
        self.settings = settings
        self.client = FakeClient(fail=fail, identity=identity)

    def build(self):
        return self.client


def make(tmp_path, **kwargs):
    from agent.config import Settings

    settings = Settings.from_env(
        {
            **ENV,
            "DATA_DIR": str(tmp_path / "data"),
            "CLONE_LIMIT": "5",
            "PLUGINS": "ops,core,clone,filestore",
        }
    )
    store = CloneStore(tmp_path / "clones")
    made = []

    def factory(built):
        bot = FakeBot(built, **kwargs)
        made.append(bot)
        return bot

    return CloneManager(settings, store, factory), store, made


def add(store, bot_id=111111111, **kwargs):
    return store.add(Clone(bot_id=bot_id, owner_id=42, token=TOKEN, **kwargs))


def test_a_started_clone_is_running_and_named(tmp_path):
    manager, store, _made = make(tmp_path)
    clone = add(store)

    import asyncio

    asyncio.run(manager.start(clone))

    state = manager.state(clone.bot_id)
    assert state.state is State.RUNNING
    assert state.username == "helper_bot"
    assert manager.counts() == {State.RUNNING: 1}


def test_a_refused_token_is_failed_with_the_reason(tmp_path):
    import asyncio

    manager, store, _made = make(tmp_path, fail=True)
    clone = add(store)

    with pytest.raises(CloneError):
        asyncio.run(manager.start(clone))

    state = manager.state(clone.bot_id)
    assert state.state is State.FAILED
    assert "UNAUTHORIZED" in state.last_error
    assert manager.is_running(clone.bot_id) is False


def test_a_client_without_an_identity_is_degraded_not_green(tmp_path):
    import asyncio

    manager, store, _made = make(tmp_path, identity=False)
    clone = add(store)

    asyncio.run(manager.start(clone))

    state = manager.state(clone.bot_id)
    assert state.state is State.DEGRADED
    assert "identity" in state.last_error
    assert manager.is_running(clone.bot_id) is True


def test_a_stored_clone_that_was_never_started_reads_as_stopped(tmp_path):
    manager, store, _made = make(tmp_path)
    add(store)

    assert manager.state(111111111).state is State.STOPPED


def test_stop_moves_through_stopping_to_stopped(tmp_path):
    import asyncio

    manager, store, made = make(tmp_path)
    clone = add(store)
    seen = []

    async def run():
        await manager.start(clone)
        original = manager.stop

        async def spy(bot_id):
            seen.append(manager.state(bot_id).state)
            return await original(bot_id)

        manager.stop = spy
        await manager.stop(clone.bot_id)

    asyncio.run(run())

    assert seen == [State.RUNNING]
    assert made[0].client.stopped == 1
    assert manager.state(clone.bot_id).state is State.STOPPED


# --- the supervisor --------------------------------------------------------


def test_a_dropped_connection_is_restarted(tmp_path):
    import asyncio

    manager, store, made = make(tmp_path)
    clone = add(store)

    async def run():
        await manager.start(clone)
        made[0].client.is_connected = False     # the client died silently
        return await manager.supervise()

    restarted = asyncio.run(run())

    assert restarted == (clone.bot_id,)
    assert manager.state(clone.bot_id).state is State.RUNNING
    assert made[-1].client.started == 1


def test_a_healthy_clone_is_left_alone(tmp_path):
    import asyncio

    manager, store, made = make(tmp_path)
    clone = add(store)

    async def run():
        await manager.start(clone)
        return await manager.supervise()

    assert asyncio.run(run()) == ()
    assert len(made) == 1


def test_the_supervisor_gives_up_after_max_attempts(tmp_path):
    import asyncio

    manager, store, made = make(tmp_path)
    clone = add(store)
    broke = SimpleNamespace(is_connected=False, started=1, stopped=0)

    async def run():
        await manager.start(clone)
        manager._running[clone.bot_id] = (made[0], broke, "helper_bot")
        # Two failures already on record.
        state = manager.state(clone.bot_id)
        state.move(State.DEGRADED, error="connection lost")
        state.attempts = 5
        manager._states.set(clone.bot_id, state)
        return await manager.supervise(max_attempts=5)

    assert asyncio.run(run()) == ()
    assert manager.state(clone.bot_id).state is State.STOPPED


def test_a_disabled_clone_is_not_restarted(tmp_path):
    import asyncio

    manager, store, made = make(tmp_path)
    clone = add(store)

    async def run():
        await manager.start(clone)
        store.update(clone.bot_id, disabled=True)
        made[0].client.is_connected = False
        return await manager.supervise()

    assert asyncio.run(run()) == ()

def test_status_reports_every_stored_clone(tmp_path):
    manager, store, _made = make(tmp_path)
    add(store, 111111111)
    add(store, 222222222)

    status = manager.status()

    assert {clone.bot_id for clone, _state in status} == {111111111, 222222222}
    assert all(state.state is State.STOPPED for _clone, state in status)
