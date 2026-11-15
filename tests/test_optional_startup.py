"""Optional integrations cannot hold the primary Telegram connection hostage."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from agent.bot import AgentBot
import agent.bot as bot_module


def test_stalled_optional_services_time_out_and_leave_controller_available(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot_module, 'OPTIONAL_STARTUP_TIMEOUT', 0.01)
        cancelled = []
        async def stall():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        owner = NS(voice=NS(start=AsyncMock(side_effect=stall)),
                   modules=NS(clones=NS(restore=AsyncMock(side_effect=stall))),
                   settings=NS(clone_limit=0))
        await asyncio.wait_for(AgentBot._start_optional_services(owner), timeout=1)
        assert len(cancelled) == 2
        owner.voice.start.assert_awaited_once()
        owner.modules.clones.restore.assert_awaited_once()
    asyncio.run(scenario())


def test_optional_voice_failure_does_not_skip_clone_restore(monkeypatch):
    async def scenario():
        owner = NS(voice=NS(start=AsyncMock(side_effect=RuntimeError('voice failure'))),
                   modules=NS(clones=NS(restore=AsyncMock(return_value=()))),
                   settings=NS(clone_limit=0))
        await AgentBot._start_optional_services(owner)
        owner.modules.clones.restore.assert_awaited_once()
    asyncio.run(scenario())


def test_required_startup_timeout_has_named_sanitized_failure(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot_module, 'REQUIRED_STARTUP_TIMEOUT', 0.01)
        owner = NS(fatal_reason='', _startup_phase=lambda phase: None)
        async def stall():
            await asyncio.Event().wait()
        try:
            await AgentBot._startup_step(owner, 'database-load', stall)
        except RuntimeError as error:
            assert 'database-load' in str(error)
            assert 'TimeoutError' in owner.fatal_reason
        else:
            raise AssertionError('startup must not hang')
        async def secret_error():
            raise OSError('postgres://private-user:password@secret-host')
        try:
            await AgentBot._startup_step(owner, 'telegram-connect', secret_error)
        except RuntimeError as error:
            assert 'telegram-connect' in str(error)
            assert 'password' not in str(error) and 'secret-host' not in owner.fatal_reason
            assert error.__suppress_context__
    asyncio.run(scenario())


def test_required_startup_step_preserves_result_and_cancellation():
    async def scenario():
        owner = NS(fatal_reason='', _startup_phase=lambda phase: None)
        assert await AgentBot._startup_step(owner, 'database-connect', AsyncMock(return_value=False)) is False
        try:
            await AgentBot._startup_step(owner, 'database-load', AsyncMock(side_effect=asyncio.CancelledError()))
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('shutdown cancellation was swallowed')
        assert owner.fatal_reason == ''
    asyncio.run(scenario())


def test_post_connection_failure_and_cancellation_always_cleanup(monkeypatch):
    from unittest.mock import Mock
    async def scenario(failure_stage, failure):
        monkeypatch.setattr(bot_module, '_install_signal_handlers', lambda event: None)
        heartbeat = asyncio.create_task(asyncio.Event().wait())
        client = NS(start=AsyncMock())
        owner = NS(database=NS(connect=AsyncMock(return_value=True), load=AsyncMock(), load_error=None),
                   logbook=NS(hydrate=AsyncMock()), users=None, premium=None,
                   runtime=NS(), modules=NS(), _client=client, fatal_reason='',
                   settings=NS(health_port=0, masked_token='masked'),
                   lease=NS(start_heartbeat=lambda event: heartbeat),
                   plugin_gate=NS(watch=lambda event: event.wait()),
                   health=NS(record_success=Mock()), events=NS(emit=Mock()),
                   _acquire_lease=AsyncMock(return_value=True),
                   _start_optional_services=AsyncMock(), _sync_commands=AsyncMock(),
                   _cleanup_services=AsyncMock())
        owner._startup_phase = AgentBot._startup_phase.__get__(owner)
        owner._startup_step = AgentBot._startup_step.__get__(owner)
        getattr(owner, failure_stage).side_effect = failure
        try:
            await AgentBot._run(owner)
        except (RuntimeError, asyncio.CancelledError):
            pass
        else:
            raise AssertionError('injected failure was swallowed')
        owner._cleanup_services.assert_awaited_once_with(client)
        client.start.assert_awaited_once()
        owner.events.emit.assert_called_once()
        assert heartbeat.cancelled()
        owner._plugin_watch.cancel()
        await asyncio.gather(owner._plugin_watch, return_exceptions=True)
    asyncio.run(scenario('_start_optional_services', asyncio.CancelledError()))
    asyncio.run(scenario('_sync_commands', RuntimeError('injected menu failure')))


def test_stalled_optional_shutdowns_do_not_prevent_telegram_disconnect(monkeypatch, caplog):
    from unittest.mock import Mock
    async def scenario():
        monkeypatch.setattr(bot_module, 'SERVICE_SHUTDOWN_TIMEOUT', 0.01)
        stopped = []
        async def stall():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)
        async def broken():
            raise RuntimeError('private-token private-database-url')
        owner = NS(voice=NS(shutdown=AsyncMock(side_effect=stall)),
                   modules=NS(clones=NS(stop_all=AsyncMock(side_effect=stall)),
                              verifier=NS(shutdown=AsyncMock(side_effect=broken)),
                              jobs=NS(shutdown=AsyncMock(side_effect=stall)),
                              storage=NS(shutdown=AsyncMock())),
                   events=NS(emit=Mock()), logbook=NS(close=AsyncMock()),
                   _shutdown=AsyncMock())
        await asyncio.wait_for(AgentBot._cleanup_services(owner, 'client'), timeout=1)
        assert len(stopped) == 3
        owner.modules.storage.shutdown.assert_awaited_once()
        owner._shutdown.assert_awaited_once_with('client')
        owner.events.emit.assert_called_once_with('stop')
        assert 'TimeoutError' in caplog.text
        assert 'private-token' not in caplog.text and 'private-database-url' not in caplog.text
    asyncio.run(scenario())
