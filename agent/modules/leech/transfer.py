"""The transfer itself: stream a URL to disk with progress, or say why not.

Progress is reported through a callback, so the module decides what a status
message looks like and this file only knows bytes. Nothing here retries
silently: a failed transfer raises :class:`~agent.platform.net.LinkError` with a
sentence a user can act on.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp

from ...platform.net import LinkError, PublicResolver, check_target, human_bytes, parse_url

#: The module's own name for the shared error type.
LeechError = LinkError

MAX_BYTES = 2 * 1024 * 1024 * 1024

CHUNK = 1024 * 256

PROGRESS_INTERVAL = 2.0

def _destination(url: str, name: str | None = None) -> Path:
    name = name or Path(urlsplit(url).path).name or "download.bin"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:80]
    if not safe or safe in (".", ".."):
        safe = "download.bin"
    return Path(tempfile.mkdtemp(prefix="leech-")) / safe

async def download(url: str, destination: Path, on_progress=None) -> int:
    """Stream *url* to *destination*; returns the byte count."""
    url = parse_url(url)
    # Also protects literal IP URLs, for which aiohttp skips its DNS resolver.
    await check_target(url)
    written = 0
    started = time.monotonic()
    last_report = 0.0
    timeout = aiohttp.ClientTimeout(total=3600, sock_connect=20, sock_read=60)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector,
                                         auto_decompress=False) as session:
            # Explicit redirects: validate literal addresses and credentials at
            # every hop, not just DNS names resolved by the connector.
            for hop in range(6):
                async with session.get(url, allow_redirects=False, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise LeechError("the server returned a redirect without a location")
                        if hop == 5:
                            raise LeechError("the server returned too many redirects")
                        url = parse_url(urljoin(url, location))
                        await check_target(url)
                        continue
                    if response.status >= 400:
                        raise LeechError(f"the server answered HTTP {response.status}")
                    if response.status != 200 or response.headers.get("Content-Range"):
                        raise LeechError("the server did not return a complete file response")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise LeechError("the server returned an unsupported content encoding")
                    try:
                        total = int(response.headers.get("Content-Length") or 0)
                    except ValueError as exc:
                        raise LeechError("the server returned an invalid file size") from exc
                    if total < 0:
                        raise LeechError("the server returned an invalid file size")
                    if total > MAX_BYTES:
                        raise LeechError(
                            f"that file is {human_bytes(total)}; the limit is {human_bytes(MAX_BYTES)}"
                        )
                    with destination.open("wb") as handle:
                        async for chunk in response.content.iter_chunked(CHUNK):
                            if written + len(chunk) > MAX_BYTES:
                                raise LeechError("the download passed the size limit")
                            handle.write(chunk)
                            written += len(chunk)
                            now = time.monotonic()
                            if on_progress is not None and now - last_report >= PROGRESS_INTERVAL:
                                last_report = now
                                await on_progress(written, total, now - started)
                    if not written:
                        raise LeechError("the server returned an empty file")
                    if total and written != total:
                        raise LeechError("the download ended before the advertised file size")
                    return written
    except BaseException:
        # Do not leave incomplete or cancelled output available for upload.
        destination.unlink(missing_ok=True)
        raise
