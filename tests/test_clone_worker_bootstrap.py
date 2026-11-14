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
