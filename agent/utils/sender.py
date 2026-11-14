"""Agent — delivery helpers.

If Telegram rejects a custom emoji, the message is retried once with plain
unicode so a premium glyph can never break a command.
"""

from __future__ import annotations

import logging
import re

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import LinkPreviewOptions
from richgram import rich_caption

from ..ui.screens import Screen
from ..ui.theme import Theme, strip_custom_emoji

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _visible_text(html_text: str) -> str:
    """What the user actually sees, for Telegram's length limits."""
    return _TAG_RE.sub("", html_text or "")


#: runs of spaces for chat text, which is right for prose and fatal for a table
#: drawn in <pre>: it squeezes every column to two spaces. Monospace blocks are
#: therefore lifted out before normalising and put back untouched.
_PRE_BLOCK_RE = re.compile(r"<pre>[\s\S]*?</pre>", re.IGNORECASE)


def to_safe_html(rich_text: str) -> str:
    """Convert rich markup into HTML that standard parse mode accepts."""
    text = rich_text or ""
    if "<pre>" not in text.lower():
        return rich_caption(text)
    pieces: list[str] = []
    cursor = 0
    for match in _PRE_BLOCK_RE.finditer(text):
        before = rich_caption(text[cursor:match.start()])
        if before:
            pieces.append(before.rstrip("\n") + "\n")
        pieces.append(match.group(0).strip() + "\n")
        cursor = match.end()
    tail = rich_caption(text[cursor:])
    if tail:
        pieces.append(tail)
    return "".join(pieces).strip()


def _no_preview() -> LinkPreviewOptions:
    return LinkPreviewOptions(is_disabled=True)


class ScreenSender:
    """Sends and edits screens, degrading gracefully at every step."""

    def __init__(self, client, theme: Theme) -> None:
        self._client = client
        self._theme = theme

    async def send(self, chat_id, screen: Screen):
        text = to_safe_html(screen.rich_text)
        try:
            return await self._post(chat_id, text, screen.keyboard)
        except Exception as exc:
            if "<tg-emoji" not in text:
                raise
            logger.warning("Custom emoji rejected (%s); retrying with unicode.", exc)
            self._theme.disable_custom_emoji()
            return await self._post(chat_id, strip_custom_emoji(text), screen.keyboard)

    async def send_photo(self, chat_id, screen: Screen, photo: str | None, *, caption_limit: int = 1024):
        """Send a screen as the caption of *photo*, falling back to plain text.

                Telegram caps captions at 1024 characters, and a picture that cannot be
                fetched must never cost the user the screen — both cases fall back to
                :meth:`send` instead of raising.
                
        """
        text = to_safe_html(screen.rich_text)
        if not photo:
            return await self.send(chat_id, screen)
        if len(_visible_text(text)) > caption_limit:
            logger.info("Screen is longer than a caption; sending it as text.")
            return await self.send(chat_id, screen)
        try:
            return await self._client.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=screen.keyboard,
            )
        except Exception as exc:  # noqa: BLE001 - the picture is decoration
            logger.warning("Start image failed (%s); sending text instead.", exc)
            return await self.send(chat_id, screen)

    async def edit(self, callback_query, screen: Screen) -> bool:
        """Edit the message a callback query points at."""
        text = to_safe_html(screen.rich_text)
        try:
            await callback_query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=screen.keyboard,
                link_preview_options=_no_preview(),
            )
            return True
        except MessageNotModified:
            return True
        except Exception as exc:
            if "<tg-emoji" not in text:
                logger.exception("Could not edit the message for a callback query.")
                return False
            logger.warning("Custom emoji rejected on edit (%s); retrying.", exc)
            self._theme.disable_custom_emoji()
            try:
                await callback_query.edit_message_text(
                    text=strip_custom_emoji(text),
                    parse_mode=ParseMode.HTML,
                    reply_markup=screen.keyboard,
                    link_preview_options=_no_preview(),
                )
                return True
            except Exception:
                logger.exception("Edit failed after removing custom emoji.")
                return False

    async def _post(self, chat_id, text: str, keyboard):
        return await self._client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options=_no_preview(),
        )
