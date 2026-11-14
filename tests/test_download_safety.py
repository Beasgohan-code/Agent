"""No network access: cover resolver binding, redirects and incomplete files."""
import asyncio
import socket
from unittest.mock import AsyncMock

import pytest

from agent.platform.net import LinkError, PublicResolver, parse_url
from agent.modules.leech import transfer


@pytest.mark.parametrize('url', ['http://[invalid', 'https://example.com:99999', 'https://example.com/\nx', 'https://example.com:bad'])
def test_malformed_urls_are_user_errors(url):
    with pytest.raises(LinkError):
        parse_url(url)


def test_resolver_rejects_mixed_answers(monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ['8.8.8.8', '127.0.0.1']]
        monkeypatch.setattr(loop, 'getaddrinfo', AsyncMock(return_value=answers))
        with pytest.raises(LinkError):
            await PublicResolver().resolve('example.com', 443)
        answers.pop()
        result = await PublicResolver().resolve('example.com', 443)
        assert result[0]['host'] == '8.8.8.8' and result[0]['port'] == 443
    asyncio.run(scenario())


class Response:
    def __init__(self, chunks=(), headers=None, status=200):
        self.chunks, self.headers, self.status = chunks, headers or {}, status
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


def wire(monkeypatch, responses):
    class Session:
        def __init__(self, **kwargs):
            # Avoid allocating a real connector in these offline tests.
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            return responses.pop(0)
    check = AsyncMock()
    monkeypatch.setattr(transfer, 'check_target', check)
    monkeypatch.setattr(transfer.aiohttp, 'TCPConnector', lambda **kwargs: None)
    monkeypatch.setattr(transfer.aiohttp, 'ClientSession', Session)
    return check


def test_redirect_is_checked_and_success_reports_progress(tmp_path, monkeypatch):
    check = wire(monkeypatch, [Response(status=302, headers={'Location': '/final'}), Response([b'abc'], {'Content-Length': '3'})])
    progress = AsyncMock()
    target = tmp_path / 'file'
    assert asyncio.run(transfer.download('https://example.com/start', target, progress)) == 3
    assert target.read_bytes() == b'abc'
    assert check.await_args_list[-1].args == ('https://example.com/final',)
    progress.assert_awaited_once()


@pytest.mark.parametrize('response', [Response([b'ab'], {'Content-Length': '3'}), Response(headers={'Content-Length': '-1'}), Response(headers={'Content-Length': 'bad'}), Response(headers={'Content-Encoding': 'gzip'}), Response(status=500)])
def test_failed_download_removes_output(tmp_path, monkeypatch, response):
    wire(monkeypatch, [response])
    target = tmp_path / 'file'
    with pytest.raises(LinkError):
        asyncio.run(transfer.download('https://example.com/file', target))
    assert not target.exists()


def test_stream_limit_and_cancel_cleanup(tmp_path, monkeypatch):
    target = tmp_path / 'file'
    monkeypatch.setattr(transfer, 'MAX_BYTES', 2)
    wire(monkeypatch, [Response([b'abc'])])
    with pytest.raises(LinkError):
        asyncio.run(transfer.download('https://example.com/file', target))
    assert not target.exists()
    wire(monkeypatch, [Response([b'a'])])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(transfer.download('https://example.com/file', target, AsyncMock(side_effect=asyncio.CancelledError)))
    assert not target.exists()


def test_redirect_to_private_target_never_requested(tmp_path, monkeypatch):
    check = wire(monkeypatch, [Response(status=302, headers={'Location': 'http://127.0.0.1/private'})])
    check.side_effect = [None, LinkError('private target')]
    with pytest.raises(LinkError, match='private target'):
        asyncio.run(transfer.download('https://example.com/start', tmp_path / 'file'))
    assert check.await_count == 2


def test_redirect_limit(tmp_path, monkeypatch):
    wire(monkeypatch, [Response(status=302, headers={'Location': '/again'}) for _ in range(6)])
    with pytest.raises(LinkError, match='too many redirects'):
        asyncio.run(transfer.download('https://example.com/start', tmp_path / 'file'))


def test_empty_dns_answers_are_not_public(monkeypatch):
    from agent.platform.net import address_is_public
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args: [])
    assert address_is_public('example.com')[0] is False
