"""Clone clients use their own database/lease lifecycle, not only client.start()."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_clone import build, FakeBot, TOKEN_A, MEMBER
from agent.modules.clone.store import Clone


def test_clone_loads_database_before_build_and_releases_on_stop(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        db = SimpleNamespace(connect=AsyncMock(return_value=True), load=AsyncMock(),
                             load_error=None, close=AsyncMock())
        events = []
        class Lease:
            async def acquire(self, **kwargs):
                events.append('lease')
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
                assert events == ['lease']
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
        voice = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError('private-session')),
                                shutdown=AsyncMock())
        workers = []
        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = voice
                self.database = SimpleNamespace(connect=AsyncMock(return_value=True), load=AsyncMock(),
                                                load_error=None, close=AsyncMock())
                workers.append(self)
        ctx.clones._factory = Worker
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
        try:
            await ctx.clones.start(record)
        except CloneError as error:
            assert 'private-session' not in str(error)
        else:
            raise AssertionError('failed voice engine was reported ready')
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
        voice = SimpleNamespace(start=AsyncMock(side_effect=blocked), shutdown=AsyncMock())
        db = SimpleNamespace(connect=AsyncMock(return_value=True), load=AsyncMock(),
                             load_error=None, close=AsyncMock())
        class Worker(FakeBot):
            def __init__(self, settings):
                super().__init__(settings)
                self.voice = voice
                self.database = db
        ctx.clones._factory = Worker
        task = asyncio.create_task(ctx.clones.start(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)))
        await entered.wait()
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not ctx.clones.running()
        voice.shutdown.assert_awaited_once()
        db.close.assert_awaited_once()
    asyncio.run(scenario())
