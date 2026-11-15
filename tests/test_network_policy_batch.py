"""Both URL admission and connection DNS answers enforce the same policy."""
import asyncio
import socket
from unittest.mock import AsyncMock

import pytest

from agent.platform import net


@pytest.mark.parametrize('url', ['https://@example.com/file', 'https://:@example.com/file',
    'http://localhost./a', 'http://localhost.localdomain./a', 'https://example.com/a b',
    'https://example.com\\@127.0.0.1/a', 'https://example.com/' + 'a'*8192])
def test_ambiguous_url_forms_refused(url):
    with pytest.raises(net.LinkError):
        net.parse_url(url)


@pytest.mark.parametrize('address', ['224.0.0.1', '239.255.255.255', 'ff02::1', '100.64.0.1',
    '127.0.0.1', '169.254.169.254', '0.0.0.0', '::', '::1', 'not-an-ip'])
def test_exact_connection_answers_refuse_nonpublic_and_multicast(monkeypatch, address):
    async def scenario():
        family = socket.AF_INET6 if ':' in address else socket.AF_INET
        answers = [(family, socket.SOCK_STREAM, 6, '', (address, 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=answers))
        assert not net.public_address(address)
        with pytest.raises(net.LinkError):
            await net.PublicResolver().resolve('example.com', 443)
    asyncio.run(scenario())


@pytest.mark.parametrize('address', ['8.8.8.8', '1.1.1.1', '2606:4700:4700::1111'])
def test_ordinary_public_answers_still_allowed(address):
    assert net.public_address(address)


def test_connection_dns_timeout_is_actionable(monkeypatch):
    async def scenario():
        monkeypatch.setattr(net, 'DNS_TIMEOUT', 0.01)
        async def hang(*args, **kwargs):
            await asyncio.Event().wait()
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', hang)
        with pytest.raises(net.LinkError, match='timed out'):
            await net.PublicResolver().resolve('example.com', 443)
    asyncio.run(scenario())


def test_preflight_dns_timeout_is_actionable(monkeypatch):
    async def scenario():
        monkeypatch.setattr(net, 'DNS_TIMEOUT', 0.01)
        pending = asyncio.get_running_loop().create_future()
        monkeypatch.setattr(asyncio.get_running_loop(), 'run_in_executor', lambda *args: pending)
        with pytest.raises(net.LinkError, match='timed out'):
            await net.check_target('https://example.com/file')
    asyncio.run(scenario())


def test_check_target_validates_scheme_before_dns(monkeypatch):
    async def scenario():
        lookup = AsyncMock()
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', lookup)
        with pytest.raises(net.LinkError):
            await net.check_target('file:///etc/passwd')
        lookup.assert_not_awaited()
    asyncio.run(scenario())
