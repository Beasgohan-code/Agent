"""Agent — one way to hand a stored file back to a user.

A vault entry can be in three states, and the sender must not care which:

* **archived** — Telegram already holds the bytes; ``reply_cached_media`` sends
  them instantly, from any instance, after any redeploy;
* **on disk** — the bytes are local; send them from the path;
* **gone** — the index remembers a file the host does not have.

Doing this in one place is what keeps ``/get``, link redemption and the music
card from each inventing their own fallback.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Extensions Telegram should play inline rather than show as a document.
VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

#: What to say when the index knows a file the host cannot produce.
MISSING = (
    "That entry is indexed but its bytes are gone — the host lost them and no "
    "storage channel has a copy. Save the file again."
)


async def send_stored(message, storage, stored, *, caption: str | None = None, **kwargs) -> bool:
    """Send one stored file to the chat *message* came from.

    Returns ``True`` when something was sent. A cached ``file_id`` wins over the
    path: it costs one API call and works on an instance that has never seen the
    upload, which is exactly what a redeploy looks like.
    """
    file_id = getattr(stored, "telegram_file_id", "")
    if file_id:
        try:
            await message.reply_cached_media(file_id, caption=caption, **kwargs)
            return True
        except Exception:  # noqa: BLE001 - a stale file_id falls back to the disk
            logger.warning("Cached media reference refused; trying local delivery")

    path = storage.path_for(stored)
    try:
        exists = path.exists()
    except OSError:
        exists = False
    if not exists:
        await message.reply(f"<b>File unavailable</b>\n{MISSING}")
        return False
    try:
        if str(stored.name).lower().endswith(VIDEO_SUFFIXES):
            await message.reply_video(
                video=str(path), file_name=stored.name, caption=caption, **kwargs
            )
        else:
            await message.reply_document(
                document=str(path), file_name=stored.name, caption=caption, **kwargs
            )
        return True
    except Exception as exc:  # noqa: BLE001 - the user gets the reason
        logger.warning("Stored media delivery refused (%s)", type(exc).__name__)
        await message.reply(f"Telegram refused that file: {type(exc).__name__}")
        return False
