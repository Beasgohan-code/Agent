"""A rolling web deploy must bind before waiting for its predecessor."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.bot import AgentBot


def test_web_standby_retries_without_bypassing_lease():
    async def scenario():
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=10000),
                              lease=SimpleNamespace(acquire=AsyncMock(side_effect=[False, True])))
        assert await AgentBot._acquire_lease(bot, asyncio.Event())
        assert bot.lease.acquire.await_count == 2
    asyncio.run(scenario())


def test_worker_retains_bounded_wait():
    async def scenario():
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=None),
                              lease=SimpleNamespace(acquire=AsyncMock(return_value=False)))
        assert not await AgentBot._acquire_lease(bot, asyncio.Event())
        bot.lease.acquire.assert_awaited_once()
    asyncio.run(scenario())


def test_standby_shutdown_cancels_lease_wait():
    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def acquire():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        stop = asyncio.Event()
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=10000),
                              lease=SimpleNamespace(acquire=acquire))
        task = asyncio.create_task(AgentBot._acquire_lease(bot, stop))
        await entered.wait()
        stop.set()
        assert not await asyncio.wait_for(task, 1)
        assert cancelled.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize('fails', [False, True])
def test_http_binds_before_startup_and_cleans_up_on_failure(monkeypatch, fails):
    async def scenario():
        events = []
        async def start(*args, **kwargs):
            events.append('http')
            return 'runner'
        async def stop(runner):
            assert runner == 'runner'
            events.append('http stopped')
        async def run():
            assert events == ['http']
            events.append('startup')
            if fails:
                raise RuntimeError('Telegram unavailable')
        monkeypatch.setattr('agent.bot.start_health_server', start)
        monkeypatch.setattr('agent.bot.stop_health_server', stop)
        lease = SimpleNamespace(stop_heartbeat=AsyncMock(), release_async=AsyncMock())
        db = SimpleNamespace(close=AsyncMock())
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=10000), health=None,
                              _health_detail=lambda: {}, _run=run, lease=lease, database=db)
        if fails:
            with pytest.raises(RuntimeError, match='Telegram unavailable'):
                await AgentBot.run(bot)
        else:
            await AgentBot.run(bot)
        assert events == ['http', 'startup', 'http stopped']
        lease.stop_heartbeat.assert_awaited_once()
        lease.release_async.assert_awaited_once()
        db.close.assert_awaited_once()
    asyncio.run(scenario())


def test_database_cleanup_runs_even_when_http_cleanup_fails(monkeypatch):
    async def scenario():
        async def stop(_runner):
            raise RuntimeError('cleanup failed')
        monkeypatch.setattr('agent.bot.stop_health_server', stop)
        lease = SimpleNamespace(stop_heartbeat=AsyncMock(), release_async=AsyncMock())
        db = SimpleNamespace(close=AsyncMock())
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=None),
                              _run=AsyncMock(), lease=lease, database=db)
        with pytest.raises(RuntimeError, match='cleanup failed'):
            await AgentBot.run(bot)
        lease.stop_heartbeat.assert_awaited_once()
        lease.release_async.assert_awaited_once()
        db.close.assert_awaited_once()
    asyncio.run(scenario())


def test_database_cleanup_runs_even_when_lease_release_fails(monkeypatch):
    async def scenario():
        monkeypatch.setattr('agent.bot.stop_health_server', AsyncMock())
        lease = SimpleNamespace(stop_heartbeat=AsyncMock(),
                                release_async=AsyncMock(side_effect=RuntimeError('release failed')))
        db = SimpleNamespace(close=AsyncMock())
        bot = SimpleNamespace(settings=SimpleNamespace(health_port=None),
                              _run=AsyncMock(), lease=lease, database=db)
        with pytest.raises(RuntimeError, match='release failed'):
            await AgentBot.run(bot)
        db.close.assert_awaited_once()
    asyncio.run(scenario())


def test_optional_shutdown_errors_do_not_skip_telegram_disconnect():
    async def scenario():
        bot = SimpleNamespace(
            voice=SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError('voice'))),
            modules=SimpleNamespace(clones=SimpleNamespace(
                stop_all=AsyncMock(side_effect=RuntimeError('clone')))),
            _shutdown=AsyncMock(),
        )
        await AgentBot._cleanup_services(bot, 'telegram client')
        bot.modules.clones.stop_all.assert_awaited_once()
        bot._shutdown.assert_awaited_once_with('telegram client')
    asyncio.run(scenario())
