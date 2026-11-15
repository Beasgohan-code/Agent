"""Clone clients use their own database/lease lifecycle, not only client.start()."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_clone import build, FakeBot, TOKEN_A, MEMBER
from agent.modules.clone.store import Clone


def test_clone_loads_database_before_build_and_releases_on_stop(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        db = SimpleNamespace(
            connect=AsyncMock(return_value=True),
            load=AsyncMock(),
            load_error=None,
            close=AsyncMock(),
        )
        events = []

        class Lease:
            async def acquire(self, **kwargs):
                events.append("lease")
                return True

            def start_heartbeat(self, stop):
                self.stop = stop
                self.task = asyncio.create_task(stop.wait())

            async def stop_heartbeat(self):
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)

            release_async = AsyncMock()

        lease = Lease()

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.database = db
                self.lease = lease

            def build(self):
                db.load.assert_awaited_once()
                assert events == ["lease"]
                return super().build()

        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        await ctx.clones.start(record)
        assert ctx.clones.is_running(record.bot_id)
        await ctx.clones.stop(record.bot_id)
        lease.release_async.assert_awaited_once()
        db.close.assert_awaited_once()
        assert not ctx.clones._lease_monitors

    asyncio.run(scenario())


def test_clone_starts_its_voice_engine_after_bot_connection(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        voice = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = voice

            async def _cleanup_services(self, client):
                await self.voice.shutdown()
                await client.stop()

        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        await ctx.clones.start(record)
        voice.start.assert_awaited_once()
        await ctx.clones.stop(record.bot_id)
        voice.shutdown.assert_awaited_once()

    asyncio.run(scenario())


def test_voice_start_failure_never_reports_clone_ready(tmp_path):
    from agent.modules.clone.manager import CloneError

    async def scenario():
        ctx, _, _ = build(tmp_path)
        voice = SimpleNamespace(
            start=AsyncMock(side_effect=RuntimeError("private-session")),
            shutdown=AsyncMock(),
        )
        workers = []

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = voice
                self.database = SimpleNamespace(
                    connect=AsyncMock(return_value=True),
                    load=AsyncMock(),
                    load_error=None,
                    close=AsyncMock(),
                )
                workers.append(self)

        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        try:
            await ctx.clones.start(record)
        except CloneError as error:
            assert "private-session" not in str(error)
        else:
            raise AssertionError("failed voice engine was reported ready")
        assert not ctx.clones.is_running(record.bot_id)
        voice.shutdown.assert_awaited_once()
        workers[0].database.close.assert_awaited_once()

    asyncio.run(scenario())


def test_cancelled_clone_start_releases_voice_and_database(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        entered = asyncio.Event()

        async def blocked():
            entered.set()
            await asyncio.Event().wait()

        voice = SimpleNamespace(
            start=AsyncMock(side_effect=blocked), shutdown=AsyncMock()
        )
        db = SimpleNamespace(
            connect=AsyncMock(return_value=True),
            load=AsyncMock(),
            load_error=None,
            close=AsyncMock(),
        )

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = voice
                self.database = db

        ctx.clones._factory = Worker
        task = asyncio.create_task(
            ctx.clones.start(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A))
        )
        await entered.wait()
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not ctx.clones.running()
        voice.shutdown.assert_awaited_once()
        db.close.assert_awaited_once()

    asyncio.run(scenario())


def test_clone_publishes_its_own_commands_after_connecting(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        workers = []

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self._sync_commands = AsyncMock()
                workers.append(self)

        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        await ctx.clones.start(record)
        worker = workers[0]
        worker._sync_commands.assert_awaited_once()
        assert worker._sync_commands.await_args.kwargs == {"reset_button": True}
        await ctx.clones.stop(record.bot_id)

    asyncio.run(scenario())


def test_clone_loads_database_log_destination_before_build(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        book = SimpleNamespace(hydrate=AsyncMock())

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.database = SimpleNamespace(
                    connect=AsyncMock(return_value=True),
                    load=AsyncMock(),
                    load_error=None,
                    close=AsyncMock(),
                )
                self.logbook = book

            def build(self):
                book.hydrate.assert_awaited_once()
                return super().build()

        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        await ctx.clones.start(record)
        await ctx.clones.stop(record.bot_id)

    asyncio.run(scenario())


def test_worker_rejects_wrong_telegram_identity_and_releases_resources(tmp_path):
    from agent.modules.clone.manager import CloneError
    import pytest

    async def scenario():
        ctx, _, _ = build(tmp_path)
        made = []

        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.client.get_me = AsyncMock(
                    return_value=SimpleNamespace(id=999, username="wrong")
                )
                made.append(self)

        ctx.clones._factory = Worker
        with pytest.raises(CloneError):
            await ctx.clones.start(
                Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
            )
        assert not ctx.clones.running()
        assert made[0].client.stopped

    asyncio.run(scenario())


def test_supervisor_stops_worker_whose_record_was_removed(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        clone = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(clone)
        ctx.clones._store.remove(clone.bot_id)
        await ctx.clones.supervise()
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_supervisor_refreshes_authoritative_store_before_keepalive(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)

        async def refresh():
            ctx.clones._store.update(record.bot_id, disabled=True)
            return ctx.clones._store.all()

        ctx.clones._store.aall = AsyncMock(side_effect=refresh)
        assert await ctx.clones.supervise() == ()
        ctx.clones._store.aall.assert_awaited_once()
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_supervisor_cannot_keep_workers_live_when_authority_is_unavailable(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._store.aall = AsyncMock(
            side_effect=RuntimeError("private-db-password")
        )
        assert await ctx.clones.supervise() == ()
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_supervisor_stops_worker_when_premium_check_fails(tmp_path, caplog):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones.eligible = AsyncMock(
            side_effect=RuntimeError("private-provider-secret")
        )
        assert await ctx.clones.supervise() == ()
        assert not ctx.clones.running()
        assert "private-provider-secret" not in caplog.text

    asyncio.run(scenario())


def test_factory_failure_is_sanitized_and_recorded_as_failed(tmp_path, caplog):
    import pytest
    from agent.modules.clone.manager import CloneError
    from agent.modules.clone.lifecycle import State

    async def scenario():
        ctx, _, _ = build(tmp_path)

        def broken(settings):
            raise RuntimeError("private-factory-token")

        ctx.clones._factory = broken
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        with pytest.raises(CloneError) as error:
            await ctx.clones.start(record)
        assert "private-factory-token" not in str(error.value)
        assert "private-factory-token" not in caplog.text
        assert ctx.clones.state(record.bot_id).state is State.FAILED
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_supervisor_stops_old_worker_after_record_is_reassigned(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._store.remove(record.bot_id)
        ctx.clones._store.add(Clone(bot_id=record.bot_id, owner_id=33, token=TOKEN_A))
        ctx.clones.eligible = AsyncMock(return_value=True)
        await ctx.clones.supervise()
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_worker_recovers_after_transient_authority_failure(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._store.aall = AsyncMock(
            side_effect=[RuntimeError("offline"), (record,)]
        )
        await ctx.clones.supervise()
        assert not ctx.clones.running()
        assert await ctx.clones.supervise() == (record.bot_id,)
        assert ctx.clones.is_running(record.bot_id)
        await ctx.clones.stop_all()

    asyncio.run(scenario())


def test_manual_stop_cancels_pending_authority_recovery(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._store.aall = AsyncMock(
            side_effect=[RuntimeError("offline"), (record,)]
        )
        await ctx.clones.supervise()
        await ctx.clones.stop(record.bot_id)
        assert await ctx.clones.supervise() == ()
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_authority_recovery_has_bounded_failed_restart_attempts(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        original = ctx.clones._factory
        calls = []

        def failing(settings):
            calls.append(settings.bot_id)
            worker = original(settings)
            worker.client.fails = True
            return worker

        ctx.clones._factory = failing
        ctx.clones._store.aall = AsyncMock(
            side_effect=[RuntimeError("offline")] + [(record,)] * 5
        )
        ticks = iter(range(0, 1000, 100))
        ctx.clones._clock = lambda: next(ticks)
        await ctx.clones.supervise(max_attempts=2)
        for _ in range(5):
            assert await ctx.clones.supervise(max_attempts=2) == ()
        assert calls == [record.bot_id, record.bot_id]
        assert not ctx.clones._pending_recovery
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_recovery_does_not_restart_disabled_or_deleted_records(tmp_path):
    async def scenario():
        for operation in ("disable", "remove"):
            ctx, _, _ = build(tmp_path / operation)
            record = ctx.clones._store.add(
                Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
            )
            await ctx.clones.start(record)

            async def unavailable():
                raise RuntimeError("offline")

            ctx.clones._store.aall = AsyncMock(side_effect=unavailable)
            await ctx.clones.supervise()
            if operation == "disable":
                ctx.clones._store.update(record.bot_id, disabled=True)
            else:
                ctx.clones._store.remove(record.bot_id)
            ctx.clones._store.aall = AsyncMock(return_value=ctx.clones._store.all())
            assert await ctx.clones.supervise() == ()
            assert not ctx.clones.running()
            assert not ctx.clones._pending_recovery

    asyncio.run(scenario())


def test_worker_recovers_after_eligibility_service_returns(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones.eligible = AsyncMock(
            side_effect=[RuntimeError("offline"), True, True]
        )
        await ctx.clones.supervise()
        assert not ctx.clones.running()
        assert not ctx.clones.record(record.bot_id).disabled
        assert await ctx.clones.supervise() == (record.bot_id,)
        await ctx.clones.stop_all()

    asyncio.run(scenario())


def test_automatic_start_rechecks_disabled_record(tmp_path):
    import pytest
    from agent.modules.clone.manager import CloneError

    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A, disabled=True)
        with pytest.raises(CloneError, match="Disabled"):
            await ctx.clones.start(record, automatic=True)
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_restore_continues_after_one_owner_eligibility_check_fails(tmp_path, caplog):
    from test_clone import TOKEN_B

    async def scenario():
        ctx, _, _ = build(tmp_path)
        first = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        second = ctx.clones._store.add(
            Clone(bot_id=222222222, owner_id=33, token=TOKEN_B)
        )

        async def eligibility(owner):
            if owner == MEMBER:
                raise RuntimeError("private-authority-key")
            return True

        ctx.clones.eligible = AsyncMock(side_effect=eligibility)
        assert await ctx.clones.restore() == (second.bot_id,)
        assert not ctx.clones.is_running(first.bot_id)
        assert ctx.clones.is_running(second.bot_id)
        assert "private-authority-key" not in caplog.text
        await ctx.clones.stop_all()

    asyncio.run(scenario())


def test_start_authority_error_is_sanitized_before_build(tmp_path):
    import pytest
    from agent.modules.clone.manager import CloneError

    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones.eligible = AsyncMock(
            side_effect=RuntimeError("private-authority-key")
        )
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        with pytest.raises(CloneError) as error:
            await ctx.clones.start(record)
        assert "private-authority-key" not in str(error.value)
        assert not ctx.clones.running()

    asyncio.run(scenario())


def test_disconnected_worker_retries_after_first_restart_fails(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._running[record.bot_id][1].is_connected = False
        original = ctx.clones._factory
        attempts = []

        def factory(settings):
            worker = original(settings)
            worker.client.fails = not attempts
            attempts.append(settings.bot_id)
            return worker

        ctx.clones._factory = factory
        assert await ctx.clones.supervise() == ()
        assert not ctx.clones.running()
        # Retry waits for exponential backoff, not the next immediate tick.
        assert await ctx.clones.supervise() == ()
        ctx.clones._clock = lambda: ctx.clones._restart_history[record.bot_id][-1] + 16
        assert await ctx.clones.supervise() == (record.bot_id,)
        assert len(attempts) == 2
        await ctx.clones.stop_all()

    asyncio.run(scenario())


def test_disconnection_recovery_obeys_restart_attempt_limit(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(
            Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        )
        await ctx.clones.start(record)
        ctx.clones._running[record.bot_id][1].is_connected = False
        original = ctx.clones._factory
        attempts = []

        def factory(settings):
            worker = original(settings)
            worker.client.fails = True
            attempts.append(settings.bot_id)
            return worker

        ctx.clones._factory = factory
        ticks = iter(range(0, 1000, 100))
        ctx.clones._clock = lambda: next(ticks)
        for _ in range(6):
            assert await ctx.clones.supervise(max_attempts=2) == ()
        assert len(attempts) == 2
        assert not ctx.clones.running()
        assert not ctx.clones._pending_recovery

    asyncio.run(scenario())


def test_successful_reconnects_do_not_reset_rolling_restart_budget(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        record = ctx.clones._store.add(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A))
        now = [0.0]
        ctx.clones._clock = lambda: now[0]
        await ctx.clones.start(record)
        for attempt in range(2):
            ctx.clones._running[record.bot_id][1].is_connected = False
            if attempt:
                assert await ctx.clones.supervise(max_attempts=2) == ()
                assert record.bot_id in ctx.clones._pending_recovery
                now[0] += 16
            assert await ctx.clones.supervise(max_attempts=2) == (record.bot_id,)
            assert ctx.clones.state(record.bot_id).attempts == 0
        ctx.clones._running[record.bot_id][1].is_connected = False
        assert await ctx.clones.supervise(max_attempts=2) == ()
        assert not ctx.clones.is_running(record.bot_id)
        assert len(ctx.clones._restart_history[record.bot_id]) == 2
        assert record.bot_id not in ctx.clones._pending_recovery
        now[0] += 3601
        assert ctx.clones._restart_permission(record.bot_id, 2) == 'ready'
    asyncio.run(scenario())
