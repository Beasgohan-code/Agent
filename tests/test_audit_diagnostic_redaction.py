"""Synthetic private values must not cross public diagnostic boundaries."""
import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.handlers.callbacks import CallbackHandlers
from agent.health import HealthMonitor
from agent.health_server import health_payload
from agent.watchdog import Watchdog


@pytest.mark.parametrize('routed', [False, True])
@pytest.mark.parametrize('answer_fails', [False, True])
def test_callback_entrypoint_does_not_log_payload(caplog, routed, answer_fails):
    caplog.set_level(logging.DEBUG)
    probe = 'SYNTHETIC_PRIVATE_CALLBACK_VALUE'
    router = SimpleNamespace(handles=lambda data: routed, dispatch=AsyncMock(return_value=True))
    handler = CallbackHandlers(None, None, router=router)
    query = SimpleNamespace(data='audit:' + probe, from_user=SimpleNamespace(id=7), answer=AsyncMock(side_effect=RuntimeError(probe) if answer_fails else None))
    asyncio.run(handler.on_callback(None, query))
    assert probe not in caplog.text
    if routed:
        router.dispatch.assert_awaited_once_with(None, query)
    else:
        query.answer.assert_awaited_once()


def test_watchdog_failure_does_not_expose_exception_body(caplog):
    caplog.set_level(logging.DEBUG)
    probe = 'SYNTHETIC_PRIVATE_PROVIDER_VALUE'
    client = SimpleNamespace(is_connected=True, get_me=AsyncMock(side_effect=RuntimeError(probe)))
    monitor = HealthMonitor()
    assert asyncio.run(Watchdog(client, monitor).probe()) is False
    assert monitor.snapshot().last_error == 'RuntimeError'
    assert probe not in json.dumps(health_payload(monitor))
    assert probe not in caplog.text
    assert monitor.snapshot().failures == 1


@pytest.mark.parametrize('path', ['watcher', 'recovery_notice', 'escalation'])
def test_moderation_background_failures_do_not_log_exception_body(caplog, monkeypatch, path):
    from agent.modules import moderation

    caplog.set_level(logging.DEBUG)
    probe = 'SYNTHETIC_PRIVATE_MODERATION_PROVIDER_VALUE'
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), from_user=SimpleNamespace(id=7))
    ctx = SimpleNamespace()

    async def scenario():
        if path == 'escalation':
            monkeypatch.setattr(moderation, 'target_is_protected', AsyncMock(return_value=False))
            client = SimpleNamespace(restrict_chat_member=AsyncMock(side_effect=RuntimeError(probe)))
            result = await moderation.escalate_warning(client, ctx, message, 7, 'mute')
            assert probe not in result and 'Escalation failed' in result
        else:
            failure = moderation.PartialKickError('safe recovery instruction') if path == 'recovery_notice' else RuntimeError(probe)
            monkeypatch.setattr(moderation, 'clean_service', AsyncMock(side_effect=failure))
            monkeypatch.setattr(moderation, 'reply', AsyncMock(side_effect=RuntimeError(probe)))
            await moderation.watch(ctx)(None, message)
    asyncio.run(scenario())
    assert probe not in caplog.text
    records = [record for record in caplog.records if record.name == moderation.__name__]
    assert records and all(record.exc_info is None for record in records)
