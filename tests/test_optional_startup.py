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
