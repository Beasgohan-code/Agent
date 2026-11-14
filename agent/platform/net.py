"""Outbound-URL safety shared by every module that fetches a link.

A bot that will fetch a URL on command is a server-side request forgery gadget
unless it refuses the addresses that only make sense from inside the host
network. Leeches, mirrors and music sources all go through here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from aiohttp.abc import AbstractResolver
from urllib.parse import urlsplit

DNS_TIMEOUT = 8.0
MAX_URL_LENGTH = 8192

BLOCKED_HOSTS = ("localhost", "localhost.localdomain", "ip6-localhost")


class LinkError(RuntimeError):
    """A URL that must be refused, with a user-facing reason."""


def parse_url(raw: str) -> str:
    """Validate a URL and return it, or raise :class:`LinkError`."""
    candidate = (raw or "").strip()
    if not candidate:
        raise LinkError("no URL given")
    if len(candidate) > MAX_URL_LENGTH:
        raise LinkError("that URL is too long")
    if "\\" in candidate or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        raise LinkError("URLs containing control characters are refused")
    try:
        parts = urlsplit(candidate)
        parts.port  # Validate malformed and out-of-range ports before network I/O.
    except ValueError as exc:
        raise LinkError("that URL has an invalid host or port") from exc
    if parts.scheme not in ("http", "https"):
        raise LinkError("only http and https URLs can be fetched")
    if not parts.hostname:
        raise LinkError("that URL has no host")
    if parts.username is not None or parts.password is not None:
        raise LinkError("URLs with embedded credentials are refused")
    if parts.hostname.lower().rstrip(".") in BLOCKED_HOSTS:
        raise LinkError("that host is not allowed")
    return candidate


def public_address(address: str) -> bool:
    """One policy for preflight and the exact connection DNS answers."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (parsed.is_global and not parsed.is_multicast
            and not parsed.is_reserved and not parsed.is_loopback
            and not parsed.is_link_local and not parsed.is_unspecified)


def address_is_public(host: str) -> tuple[bool, str]:
    """Resolve *host* and refuse loopback/private/link-local targets."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return False, f"could not resolve that host ({type(exc).__name__})"
    if not infos:
        return False, "that host has no usable addresses"
    for info in infos:
        address = info[4][0]
        if not public_address(address):
            return False, "that host resolves to a private or reserved address"
    return True, ""


async def check_target(url: str) -> None:
    """Raise :class:`LinkError` when *url* must not be fetched."""
    host = urlsplit(parse_url(url)).hostname or ""
    loop = asyncio.get_running_loop()
    try:
        ok, reason = await asyncio.wait_for(
            loop.run_in_executor(None, address_is_public, host), timeout=DNS_TIMEOUT)
    except TimeoutError:
        raise LinkError("host validation timed out; try again later") from None
    if not ok:
        raise LinkError(reason)


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover


class PublicResolver(AbstractResolver):
    """Validate the exact DNS answers used by aiohttp, including redirects.

    Resolving once for a preflight and again for the connection is not a safety
    boundary: DNS can change between the two. Return only the checked answers
    to the connector, rejecting mixed public/private sets in their entirety.
    """

    async def resolve(self, host, port=0, family=socket.AF_INET):
        loop = asyncio.get_running_loop()
        try:
            answers = await asyncio.wait_for(loop.getaddrinfo(
                host, port, family=family, type=socket.SOCK_STREAM
            ), timeout=DNS_TIMEOUT)
        except TimeoutError:
            raise LinkError("host validation timed out; try again later") from None
        except OSError as exc:
            raise LinkError("could not resolve that host") from exc
        if not answers:
            raise LinkError("that host has no usable addresses")
        results = []
        for address_family, _, proto, _, address in answers:
            if not public_address(address[0]):
                raise LinkError("that host resolves to a private or reserved address")
            results.append(dict(hostname=host, host=address[0], port=port,
                                family=address_family, proto=proto,
                                flags=socket.AI_NUMERICHOST))
        return results

    async def close(self):
        """No persistent resolver resources to release."""
