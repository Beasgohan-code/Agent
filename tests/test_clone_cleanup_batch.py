"""Clone partial-start cleanup cannot leak jobs, archives or clients."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules.clone.manager import CloneManager, CloneError
from agent.modules.clone.store import Clone
from test_clone import build, FakeBot, TOKEN_A, MEMBER


def worker():
    return SimpleNamespace(voice=SimpleNamespace(shutdown=AsyncMock()),
        modules=SimpleNamespace(**{name: SimpleNamespace(shutdown=AsyncMock()) for name in ('jobs', 'storage', 'verifier')}))


def test_fallback_cleans_every_service_and_client():
    async def scenario():
        bot = worker()
        client = SimpleNamespace(stop=AsyncMock())
        await CloneManager._cleanup_worker(bot, client)
        bot.voice.shutdown.assert_awaited_once()
        for name in ('jobs', 'storage', 'verifier'):
            getattr(bot.modules, name).shutdown.assert_awaited_once()
        client.stop.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize('broken', ['aggregate', 'voice', 'jobs', 'storage', 'verifier'])
def test_cleanup_failure_never_skips_client_disconnect(broken, caplog):
    async def scenario():
        bot = worker()
        client = SimpleNamespace(stop=AsyncMock())
        error = RuntimeError('bot-token private-session')
        if broken == 'aggregate':
            bot._cleanup_services = AsyncMock(side_effect=error)
        else:
            service = bot.voice if broken == 'voice' else getattr(bot.modules, broken)
            service.shutdown.side_effect = error
        await CloneManager._cleanup_worker(bot, client)
        client.stop.assert_awaited_once()
        assert 'bot-token' not in caplog.text and 'private-session' not in caplog.text
    asyncio.run(scenario())


def test_successful_aggregate_cleanup_is_not_duplicated():
    async def scenario():
        bot = worker()
        bot._cleanup_services = AsyncMock()
        client = SimpleNamespace(stop=AsyncMock())
        await CloneManager._cleanup_worker(bot, client)
        bot._cleanup_services.assert_awaited_once_with(client)
        bot.voice.shutdown.assert_not_awaited()
        client.stop.assert_not_awaited()
    asyncio.run(scenario())


def test_failed_start_releases_partial_module_services(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        made = []
        class PartialBot(FakeBot):
            def __init__(self, settings):
                super().__init__(settings, fails=True)
                self.modules = worker().modules
                made.append(self)
        ctx.clones._factory = PartialBot
        clone = ctx.clones._store.add(Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A))
        with pytest.raises(CloneError):
            await ctx.clones.start(clone)
        for name in ('jobs', 'storage', 'verifier'):
            getattr(made[0].modules, name).shutdown.assert_awaited_once()
        assert made[0].client.stopped
        assert not ctx.clones.is_running(clone.bot_id)
    asyncio.run(scenario())


@pytest.mark.parametrize('broken', ['stop_heartbeat', 'release_async', 'close'])
def test_resource_release_failures_do_not_skip_other_release_steps(broken, caplog):
    async def scenario():
        lease = SimpleNamespace(stop_heartbeat=AsyncMock(), release_async=AsyncMock())
        database = SimpleNamespace(close=AsyncMock())
        getattr(database if broken == 'close' else lease, broken).side_effect = RuntimeError('private database password')
        await CloneManager._release_worker(SimpleNamespace(lease=lease, database=database))
        lease.stop_heartbeat.assert_awaited_once()
        lease.release_async.assert_awaited_once()
        database.close.assert_awaited_once()
        assert 'private database password' not in caplog.text
    asyncio.run(scenario())
