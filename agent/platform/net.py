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

BLOCKED_HOSTS = ("localhost", "localhost.localdomain", "ip6-localhost")


class LinkError(RuntimeError):
    """A URL that must be refused, with a user-facing reason."""


def parse_url(raw: str) -> str:
    """Validate a URL and return it, or raise :class:`LinkError`."""
    candidate = (raw or "").strip()
    if not candidate:
        raise LinkError("no URL given")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
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
    if parts.username or parts.password:
        raise LinkError("URLs with embedded credentials are refused")
    if parts.hostname.lower() in BLOCKED_HOSTS:
        raise LinkError("that host is not allowed")
    return candidate


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
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - malformed resolution
            return False, "that host returned an invalid address"
        if (
            not parsed.is_global
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
        ):
            return False, "that host resolves to a private or reserved address"
    return True, ""


async def check_target(url: str) -> None:
    """Raise :class:`LinkError` when *url* must not be fetched."""
    host = urlsplit(url).hostname or ""
    loop = asyncio.get_running_loop()
    ok, reason = await loop.run_in_executor(None, address_is_public, host)
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
            answers = await loop.getaddrinfo(
                host, port, family=family, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise LinkError("could not resolve that host") from exc
        if not answers:
            raise LinkError("that host has no usable addresses")
        results = []
        for address_family, _, proto, _, address in answers:
            try:
                public = ipaddress.ip_address(address[0]).is_global
            except ValueError:
                public = False
            if not public:
                raise LinkError("that host resolves to a private or reserved address")
            results.append(dict(hostname=host, host=address[0], port=port,
                                family=address_family, proto=proto,
                                flags=socket.AI_NUMERICHOST))
        return results

    async def close(self):
        """No persistent resolver resources to release."""
