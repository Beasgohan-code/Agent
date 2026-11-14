"""Fresh filesystems and stale LOG_CHANNEL must not undo committed settings."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.config import Settings
from agent.bot import AgentBot
from agent.platform.db import Database
from agent.platform.logbook import LogBook, LogSettingsError
from test_logbook import ENV, FakeClient


def test_database_log_write_failure_keeps_old_memory_and_suppresses_stale_routing(tmp_path):
    async def scenario():
        class Connection:
            async def execute(self, *args, **kwargs):
                raise RuntimeError('private connection error')
        class Pool:
            def acquire(self, **kwargs):
                class Acquired:
                    async def __aenter__(self):
                        return Connection()
                    async def __aexit__(self, *args):
                        pass
                return Acquired()
        book = LogBook(tmp_path, channel_id=-1001, db=SimpleNamespace(connected=True, _pool=Pool(), scope='main:1'))
        with pytest.raises(LogSettingsError) as error:
            await book.configure(-2002)
        assert 'private connection error' not in str(error.value)
        assert book.channel_id == -1001
        book.client = FakeClient()
        assert await book.post('start') is False
        assert not book.client.sent
        assert not (tmp_path / 'logbook.json').exists()
    asyncio.run(scenario())


def test_bot_logbook_is_wired_to_its_database(tmp_path):
    bot = AgentBot(Settings.from_env({**ENV, 'DATABASE_URL': 'postgresql://unused/test', 'DATA_DIR': str(tmp_path)}))
    assert bot.logbook._db is bot.database


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_real_pg_log_settings_survive_fresh_redeploy_clear_and_tenant_changes(tmp_path):
    async def scenario():
        url = os.environ['AGENT_TEST_DATABASE_URL']
        scope = 'logbook-test:' + uuid.uuid4().hex
        db = Database(url, scope=scope, required=True)
        clone_db = Database(url, scope=scope + ':clone', required=True)
        try:
            assert await db.connect() and await clone_db.connect()
            await db.load()
            first = LogBook(tmp_path / 'old', channel_id=-1001, owner_id=11, db=db)
            await first.hydrate()
            assert first.channel_id == -1001  # no row -> environment default
            await first.configure(-2002)
            # New client/connection and an entirely new filesystem, without flush().
            await db.close()
            assert await db.connect()
            await db.load()
            restarted = LogBook(tmp_path / 'new', channel_id=-3003, owner_id=11, db=db)
            await restarted.hydrate()
            assert restarted.channel_id == -2002
            clone = LogBook(tmp_path / 'clone', channel_id=-4004, owner_id=22, db=clone_db)
            await clone.hydrate()
            assert clone.channel_id == -4004
            await clone.configure(-5005)
            await restarted.hydrate()
            assert restarted.channel_id == -2002
            # Explicit NULL is a saved override, not a missing setting.
            await restarted.configure(None)
            cleared = LogBook(tmp_path / 'fresh', channel_id=-9999, owner_id=11, db=db)
            await cleared.hydrate()
            assert cleared.channel_id is None and cleared.destination() == 11
            await clone.hydrate()
            assert clone.channel_id == -5005
            assert not list(tmp_path.rglob('logbook.json'))
            # /log can re-read a committed change instead of showing old cache.
            await first.configure(-6006)
            await cleared.hydrate()
            assert cleared.channel_id == -6006
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_log_settings WHERE tenant=$1 OR tenant=$2', scope, scope + ':clone')
            await db.close()
            await clone_db.close()
    asyncio.run(scenario())


def test_required_database_log_load_failure_prevents_telegram_start():
    async def scenario():
        bot = SimpleNamespace(settings=SimpleNamespace(db_required=True), fatal_reason=None,
                              database=SimpleNamespace(connect=AsyncMock(return_value=True),
                                  load=AsyncMock(), load_error=None),
                              logbook=SimpleNamespace(hydrate=AsyncMock(side_effect=LogSettingsError('read failed'))),
                              build=AsyncMock())
        await AgentBot._run(bot)
        assert 'log destination' in bot.fatal_reason
        bot.build.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_setlog_command_and_internal_clear_persist(tmp_path):
    from agent.modules import ops
    from test_logbook import make_ctx, FakeMessage
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='log-commands-test:' + uuid.uuid4().hex)
        try:
            assert await db.connect()
            client = FakeClient()
            ctx = make_ctx(tmp_path / 'before', client)
            ctx.logbook = LogBook(tmp_path / 'before', channel_id=-1001, owner_id=11, db=db)
            await ctx.logbook.hydrate()
            command = FakeMessage('/setlog -2002')
            await ops.build(ctx)[1]['setlog'](client, command)
            assert 'Saved in postgres' in command.replies[-1]
            async with db._pool.acquire() as connection:
                assert await connection.fetchval('SELECT channel_id FROM agent_log_settings WHERE tenant=$1', db.scope) == -2002
            after = LogBook(tmp_path / 'after', channel_id=-3003, owner_id=11, db=db)
            await after.hydrate()
            assert after.channel_id == -2002
            ctx.logbook = after
            await after.configure(None)
            cleared = LogBook(tmp_path / 'empty', channel_id=-4444, owner_id=11, db=db)
            await cleared.hydrate()
            assert cleared.channel_id is None and cleared.destination() == 11
        finally:
            if db.connected:
                async with db._pool.acquire() as connection:
                    await connection.execute('DELETE FROM agent_log_settings WHERE tenant=$1', db.scope)
            await db.close()
    asyncio.run(scenario())
