"""Privacy-safe durable error reports, not raw tracebacks or update forwarding."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform.incidents import ErrorIncidents
from agent.platform.db import Database
from agent.platform.logbook import format_event, LogBook
from agent.platform.events import EventLog
from agent.modules import ops
from test_logbook import make_ctx, FakeClient, FakeMessage
from agent.bot import AgentBot
from agent.config import Settings
from test_logbook import ENV


def test_errors_are_tagged_plural_and_raw_exception_content_is_never_used(tmp_path):
    async def scenario():
        class SecretError(Exception):
            def __str__(self):
                raise AssertionError('exception arguments must not be stringified')
        service = ErrorIncidents(None)
        report = await service.capture(SecretError('private-key'), object())
        assert report['saved'] is False and report['notify'] is True
        assert 'private-key' not in repr(report)
        again = await service.capture(SecretError('different-private-key'), object())
        assert again['notify'] is False
        assert '#Errors' in format_event('error', {'incident': report['incident_id']})
    asyncio.run(scenario())


def test_error_boundary_sends_safe_metadata_not_update_or_credentials(tmp_path):
    async def scenario():
        bot = AgentBot(Settings.from_env({**ENV, 'DATA_DIR': str(tmp_path)}))
        events = EventLog()
        bot.events = events
        await bot._on_error(None, ValueError('TOKEN_AND_PRIVATE_MESSAGE'), object(),
                            SimpleNamespace(text='PRIVATE_UPDATE'), {}, {})
        report = events.recent(1)[0]
        assert report['kind'] == 'error'
        assert 'TOKEN_AND_PRIVATE_MESSAGE' not in repr(report)
        assert 'PRIVATE_UPDATE' not in repr(report)
        assert report['saved'] is False
    asyncio.run(scenario())


def test_errors_command_is_owner_only_and_private(tmp_path):
    async def scenario():
        from agent.ui.theme import Theme
        ctx = make_ctx(tmp_path, FakeClient())
        ctx.theme = Theme()
        ctx.incidents = SimpleNamespace(recent=AsyncMock(return_value=[]))
        handler = ops.build(ctx)[1]['errors']
        await handler(None, FakeMessage('/errors', uid=404))
        ctx.incidents.recent.assert_not_awaited()
        await handler(None, FakeMessage('/errors', uid=11, chat_id=-100))
        ctx.incidents.recent.assert_not_awaited()
        await handler(None, FakeMessage('/errors', uid=11, chat_id=11))
        ctx.incidents.recent.assert_awaited_once()
    asyncio.run(scenario())


def test_runtime_requires_postgres_even_if_legacy_flag_was_disabled():
    async def scenario():
        bot = SimpleNamespace(settings=SimpleNamespace(db_required=False), database=None,
                              fatal_reason=None, build=AsyncMock())
        await AgentBot._run(bot)
        assert 'Database is required' in bot.fatal_reason
        bot.build.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable Database required')
def test_real_pg_error_incidents_aggregate_survive_restart_and_isolate_tenants(tmp_path):
    async def scenario():
        scope = 'errors-test:' + uuid.uuid4().hex
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope)
        other = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope + ':other')
        try:
            assert await db.connect() and await other.connect()
            service = ErrorIncidents(db)
            results = await asyncio.gather(*(service.capture(ValueError('secret-value'), object()) for _ in range(8)))
            assert all(item['saved'] for item in results)
            assert sum(item['notify'] for item in results) == 1
            assert len({item['incident_id'] for item in results}) == 1
            rows = await service.recent()
            assert len(rows) == 1 and rows[0]['occurrences'] == 8
            assert not await ErrorIncidents(other).recent()
            await db.close()
            assert await db.connect()
            assert (await ErrorIncidents(db).recent())[0]['occurrences'] == 8
            async with db._pool.acquire() as conn:
                raw = await conn.fetchval('SELECT frames::text FROM agent_error_incidents WHERE tenant=$1', scope)
                assert 'secret-value' not in raw
            for i in range(105):
                await service.capture(type(f'Incident{i}', (Exception,), {})(), object())
            async with db._pool.acquire() as conn:
                assert await conn.fetchval('SELECT count(*) FROM agent_error_incidents WHERE tenant=$1', scope) == 100
            # Log delivery uses the same #Errors tag, without requiring raw detail.
            book = LogBook(tmp_path, owner_id=11)
            book.client = FakeClient()
            assert await book.post('error', incident=rows[0]['incident_id'])
            assert '#Errors' in book.client.sent[0][1]
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_error_incidents WHERE tenant=$1 OR tenant=$2', scope, scope + ':other')
            await db.close()
            await other.close()
    asyncio.run(scenario())


def test_configured_database_never_reads_or_writes_local_settings_even_optional(tmp_path):
    from agent.platform.db import load_document, save_document
    from agent.platform.runtime import PluginRuntime
    from agent.platform.manifest import PluginRegistry
    path = tmp_path / 'state.json'
    path.write_text('{"disabled":["music"]}')
    db = Database('postgresql://unused/test', required=False)
    assert load_document(db, 'test', path, {}) == {}
    with pytest.raises(RuntimeError, match='refusing local'):
        save_document(db, 'test', path, {'new': True})
    runtime = PluginRuntime(PluginRegistry(), state_path=path, db=db)
    assert not runtime.wants_disabled('music')
    with pytest.raises(RuntimeError, match='refusing local'):
        runtime._save()
    assert path.read_text() == '{"disabled":["music"]}'


def test_error_alert_throttle_memory_is_bounded():
    async def scenario():
        service = ErrorIncidents(None)
        for i in range(220):
            await service.capture(type(f'Error{i}', (Exception,), {})(), object())
        assert len(service._recent) == 200
    asyncio.run(scenario())
