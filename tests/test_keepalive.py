import asyncio

import pytest

from agent.keepalive import KeepAlive, health_target
from agent.config import Settings


@pytest.mark.parametrize('origin', ['https://u:p@example.com', 'https://example.com/?secret=x',
                                   'file:///tmp/x', 'https://example.com/path', 'https://example.com/#x'])
def test_reject_non_origin(origin):
    with pytest.raises(ValueError):
        health_target(origin)


def test_target_and_disabled():
    assert health_target('https://example.com/') == 'https://example.com/health'
    assert KeepAlive().snapshot()['enabled'] is False
    asyncio.run(KeepAlive().run())


def test_success_failure_and_recovery():
    class Response:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    class Session:
        def get(self, url, **kwargs):
            assert url == 'https://example.com/health'
            assert kwargs == {'allow_redirects': False}
            return response
    response = Response()
    async def scenario():
        service = KeepAlive('https://example.com')
        session = Session()
        await service.probe(session)
        assert service.successes == 1
        response.status = 503
        await service.probe(session)
        assert service.last_error == 'RuntimeError'
        assert service.consecutive_failures == 1
        response.status = 200
        await service.probe(session)
        assert service.consecutive_failures == 0
        assert service.last_error is None
        assert service.attempts == 3
        assert 'example.com' not in str(service.snapshot())
    asyncio.run(scenario())


def test_render_origin_config():
    settings = Settings.from_env({'BOT_TOKEN': '123456:' + 'a'*35, 'API_ID': '123',
                                  'API_HASH': 'a'*32, 'RENDER_EXTERNAL_URL': 'https://example.com'})
    assert settings.keepalive_origin == 'https://example.com'


def test_run_is_cancelled_cleanly(monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        monkeypatch.setattr('agent.keepalive.aiohttp.ClientSession', lambda **kwargs: Session())
        service = KeepAlive('https://example.com')
        async def probe(session):
            entered.set()
        monkeypatch.setattr(service, 'probe', probe)
        task = asyncio.create_task(service.run())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
