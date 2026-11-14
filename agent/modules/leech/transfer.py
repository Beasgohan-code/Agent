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
from urllib.parse import urlsplit

import aiohttp

from ...platform.net import LinkError, human_bytes

#: The module's own name for the shared error type.
LeechError = LinkError

MAX_BYTES = 2 * 1024 * 1024 * 1024

CHUNK = 1024 * 256

PROGRESS_INTERVAL = 2.0

def _destination(url: str) -> Path:
    name = Path(urlsplit(url).path).name or "download.bin"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:80]
    return Path(tempfile.mkdtemp(prefix="leech-")) / (safe or "download.bin")

async def download(url: str, destination: Path, on_progress=None) -> int:
    """Stream *url* to *destination*; returns the byte count."""
    written = 0
    started = time.monotonic()
    last_report = 0.0
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status >= 400:
                raise LeechError(f"the server answered HTTP {response.status}")
            total = int(response.headers.get("Content-Length") or 0)
            if total and total > MAX_BYTES:
                raise LeechError(
                    f"that file is {human_bytes(total)}; the limit is {human_bytes(MAX_BYTES)}"
                )
            with destination.open("wb") as handle:
                async for chunk in response.content.iter_chunked(CHUNK):
                    handle.write(chunk)
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise LeechError("the download passed the size limit")
                    now = time.monotonic()
                    if on_progress is not None and now - last_report >= PROGRESS_INTERVAL:
                        last_report = now
                        await on_progress(written, total, now - started)
    return written
