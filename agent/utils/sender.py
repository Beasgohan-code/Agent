"""Agent — delivery helpers.

Screens are authored as rich markup and delivered as standard Telegram HTML
assembled by richgram's public rich→HTML normaliser, which keeps the tags
Telegram accepts and drops the rich-only ones. Inline keyboards ride along as
native reply markup, so callback navigation never depends on rich rendering.

If Telegram rejects a custom emoji, the message is retried once with plain
unicode so a premium glyph can never break a command.
"""

from __future__ import annotations

import logging

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import LinkPreviewOptions
from richgram import rich_caption

from ..ui.screens import Screen
from ..ui.theme import Theme, strip_custom_emoji

logger = logging.getLogger(__name__)


def to_safe_html(rich_text: str) -> str:
    """Convert rich markup into HTML that standard parse mode accepts."""
    # rich_caption is richgram's public rich->standard-HTML normaliser.
    return rich_caption(rich_text)


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
