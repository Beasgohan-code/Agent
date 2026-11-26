import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from agent.platform.deeplinks import DeepLinkRouter


@pytest.mark.parametrize('prefix,handler', [('private link', AsyncMock()), ('link', None), ('link:token', AsyncMock())])
def test_invalid_registration_does_not_reserve_route(prefix, handler):
    router = DeepLinkRouter()
    with pytest.raises(ValueError):
        router.register(prefix, handler)
    assert router.prefixes() == []


def test_failure_logs_no_private_token_and_informs_user(caplog):
    async def scenario():
        router = DeepLinkRouter()
        action = AsyncMock(side_effect=RuntimeError('SECRET_PROVIDER'))
        router.register('link', action)
        message = SimpleNamespace(reply=AsyncMock())
        assert await router.dispatch(None, message, 'link_SECRET_TOKEN')
        action.assert_awaited_once()
        message.reply.assert_awaited_once()
        assert 'not confirmed' in message.reply.await_args.args[0]
        assert 'SECRET' not in caplog.text
    asyncio.run(scenario())


def test_reply_failure_is_contained_without_token_leak(caplog):
    async def scenario():
        router = DeepLinkRouter()
        router.register('link', AsyncMock(side_effect=RuntimeError('SECRET_PROVIDER')))
        message = SimpleNamespace(reply=AsyncMock(side_effect=RuntimeError('SECRET_REPLY')))
        assert await router.dispatch(None, message, 'link_SECRET_TOKEN')
        assert 'SECRET' not in caplog.text
    asyncio.run(scenario())


def test_cancelled_operation_is_not_converted_to_failure_reply():
    async def scenario():
        router = DeepLinkRouter()
        router.register('link', AsyncMock(side_effect=asyncio.CancelledError()))
        message = SimpleNamespace(reply=AsyncMock())
        with pytest.raises(asyncio.CancelledError):
            await router.dispatch(None, message, 'link_token')
        message.reply.assert_not_awaited()
    asyncio.run(scenario())


def test_start_entrypoint_does_not_log_payload(caplog):
    import logging
    from agent.handlers.commands import CommandHandlers
    caplog.set_level(logging.INFO)
    async def scenario():
        router = DeepLinkRouter()
        router.register('link', AsyncMock())
        message = SimpleNamespace(text='/start link_SECRET_ENTRY', from_user=SimpleNamespace(id=7))
        await CommandHandlers(None, None, deeplinks=router).start(None, message)
        assert 'SECRET_ENTRY' not in caplog.text
    asyncio.run(scenario())


def test_execution_gate_does_not_log_redemption_exception(caplog):
    import logging
    from agent.platform.execution import PluginGate
    caplog.set_level(logging.ERROR)
    async def scenario():
        runtime = SimpleNamespace(wants_disabled=lambda _: False,
                                  registry=SimpleNamespace(is_enabled=lambda _: True))
        gate = PluginGate(None, runtime, SimpleNamespace())
        handler = gate.wrap('linkshare', AsyncMock(side_effect=RuntimeError('SECRET_GATE')))
        message = SimpleNamespace(chat=SimpleNamespace(id=7), reply=AsyncMock())
        await handler(None, message, 'SECRET_TOKEN')
        assert 'SECRET_GATE' not in caplog.text
    asyncio.run(scenario())
