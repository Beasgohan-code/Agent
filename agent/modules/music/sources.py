"""Turning a command or a reply into something the engine can stream.

Input resolution is separate from native offline-only playback admission:

* a URL — validated here before anything is fetched (http/https, no embedded
  credentials, not a private address). Native playback currently refuses remote
  URLs until a bounded mediated-fetch path is implemented;
* a Telegram media reply — downloaded by the bot (≤20 MB, the Bot API cap) and
  streamed from disk.

YouTube video links use the shared TypeTube public-cluster resolver when its
Node.js dependency is installed. Signed stream URLs are session-only; automatic
expiry refresh and arbitrary-site extraction are not implemented.
"""

from __future__ import annotations

import logging
import asyncio
import stat
from pathlib import Path

from ...platform.net import LinkError, check_target, parse_url
from ..leech.typetube import youtube_url, resolve_audio

logger = logging.getLogger(__name__)

#: Telegram's Bot API download cap for bots.
BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT = 45
MEDIA_ATTRIBUTES = ("audio", "video", "document", "voice")


class SourceError(RuntimeError):
    """A request that cannot be turned into a stream, with a reason for the user."""


def name_of(message) -> str:
    """A human title for a replied media object."""
    replied = getattr(message, "reply_to_message", None)
    for attribute in MEDIA_ATTRIBUTES:
        media = getattr(replied, attribute, None) if replied is not None else None
        if media is None:
            continue
        for field_name in ("title", "file_name"):
            value = getattr(media, field_name, None)
            if value:
                return str(value)[:120]
        return attribute.capitalize()
    return "track"


def replied_media(message):
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    for attribute in MEDIA_ATTRIBUTES:
        media = getattr(replied, attribute, None)
        if media is not None:
            return replied, media
    return None


async def resolve(message, arg: str | None) -> tuple[str, str]:
    """(source, title) for *message*; raises :class:`SourceError` when it cannot."""
    if arg:
        try:
            url = parse_url(arg)
            await check_target(url)
            youtube = youtube_url(url)
            if youtube:
                source, filename = await resolve_audio(youtube)
                return source, filename.rsplit('.', 1)[0]
        except (LinkError, ValueError) as exc:
            raise SourceError(str(exc)) from exc
        return url, Path(url.split("?")[0]).name or url

    found = replied_media(message)
    if found is None:
        raise SourceError(
            "give me a direct audio/video URL, or reply to a file with <code>/play</code>"
        )
    replied, media = found
    size = getattr(media, "file_size", 0) or 0
    if type(size) is not int or size < 0:
        raise SourceError('Invalid media size metadata. Try another file.')
    if size > BOT_DOWNLOAD_LIMIT:
        raise SourceError(
            "that file is larger than the Bot API lets me download (20 MB)"
        )
    async def progress(current, total):
        if current > BOT_DOWNLOAD_LIMIT:
            raise SourceError("Downloaded media exceeds the music size limit.")

    try:
        downloaded = await asyncio.wait_for(replied.download(progress=progress), timeout=DOWNLOAD_TIMEOUT)
    except asyncio.TimeoutError:
        raise SourceError("Media download timed out. Retry with supported media.") from None
    except SourceError:
        raise
    except Exception as exc:
        logger.warning("#Errors Music media download failed (%s)", type(exc).__name__)
        raise SourceError("Media download failed. Retry with supported media.") from None
    if not downloaded:
        raise SourceError("Telegram returned no file to play")
    try:
        path = Path(downloaded)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise SourceError("Telegram returned no usable media file.")
        if info.st_size > BOT_DOWNLOAD_LIMIT:
            raise SourceError("Downloaded media exceeds the music size limit.")
    except (OSError, TypeError, ValueError):
        raise SourceError("Downloaded media is unavailable. Retry the request.") from None
    return str(path), name_of(message)
