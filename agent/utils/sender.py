"""Agent — delivery helpers.

If Telegram rejects a custom emoji, the message is retried once with plain
unicode so a premium glyph can never break a command.
"""

from __future__ import annotations

import html
from copy import copy
import logging
import re

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import InputRichMessage, InputRichMessageMedia, InputMediaPhoto, LinkPreviewOptions
from richgram import rich_caption

from ..ui import tables
from ..ui.screens import Screen
from . import rich as rich_utils
from ..ui.theme import Theme, strip_custom_emoji

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _visible_text(html_text: str) -> str:
    """What the user actually sees, for Telegram's length limits."""
    return html.unescape(_TAG_RE.sub("", html_text or ""))


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


def _emoji_rejected(exc: Exception) -> bool:
    """Only explicit emoji errors justify stripping decorative entities."""
    reason = f"{type(exc).__name__} {exc}".upper()
    return any(code in reason for code in (
        "CUSTOM_EMOJI_INVALID", "CUSTOMEMOJIINVALID", "CUSTOM_EMOJI_NOT_ALLOWED",
        "CUSTOMEMOJINOTALLOWED", "CUSTOM_EMOJI_ID_INVALID",
        "CAN'T PARSE ENTITIES", "CANNOT PARSE ENTITIES",
    ))


def _photo_rejected(exc: Exception) -> bool:
    reason = f"{type(exc).__name__} {exc}".upper()
    return any(code in reason for code in (
        "PHOTO_INVALID", "PHOTOINVALID", "PHOTO_EXT_INVALID", "PHOTOEXTINVALID",
        "PHOTO_INVALID_DIMENSIONS", "PHOTOINVALIDDIMENSIONS",
        "WEBPAGE_CURL_FAILED", "WEBPAGECURLFAILED", "WEBPAGE_MEDIA_EMPTY",
        "WEBPAGEMEDIAEMPTY", "MEDIA_EMPTY", "MEDIAEMPTY", "IMAGE_PROCESS_FAILED",
        "IMAGEPROCESSFAILED", "WRONG_FILE_IDENTIFIER", "EXTERNAL_URL_INVALID",
    ))


def _uneditable(exc):
    reason = f"{type(exc).__name__} {exc}".upper().replace("_", "")
    return any(code in reason for code in (
        "MESSAGEIDINVALID", "MESSAGEEDITTIMEEXPIRED", "MESSAGEAUTHORREQUIRED",
        "MESSAGECANTBEEDITED", "MESSAGECANNOTBEEDITED",
    ))


def _has_emoji(screen):
    return '<tg-emoji' in screen.rich_text or any(
        getattr(button, 'icon_custom_emoji_id', None)
        for row in getattr(screen.keyboard, 'inline_keyboard', ()) for button in row)


def _plain_screen(screen):
    # Copy only the presentation fields; callbacks, styles and actions survive.
    keyboard = screen.keyboard
    if hasattr(keyboard, 'inline_keyboard'):
        keyboard = copy(keyboard)
        keyboard.inline_keyboard = [[copy(button) for button in row] for row in keyboard.inline_keyboard]
        for row in keyboard.inline_keyboard:
            for button in row:
                button.icon_custom_emoji_id = None
    text = strip_custom_emoji(screen.rich_text)
    if hasattr(screen.rich_text, 'classic'):
        text = tables.Panel(text, strip_custom_emoji(screen.rich_text.classic))
    return Screen(text, keyboard)


class ScreenSender:
    """Sends and edits screens, degrading gracefully at every step."""

    def __init__(self, client, theme: Theme) -> None:
        self._client = client
        self._theme = theme

    async def _send_rich(self, chat_id, screen: Screen):
        """A real rich message: native tables, headings, collapsible blocks.

        Returns the message, or ``None`` when this deployment cannot have one —
        then the caller sends classic HTML. Ambiguous transport failures raise.
        """
        if not tables.rich_enabled() or not rich_utils.needs_rich(screen.rich_text):
            return None
        client = self._client
        if not rich_utils.available(client):
            return None
        try:
            return await client.send_rich_message(
                chat_id=chat_id,
                rich_text=InputRichMessage(html=screen.rich_text),
                reply_markup=screen.keyboard,
            )
        except Exception as exc:  # noqa: BLE001 - downgrade, never lose the screen
            if not rich_utils._refused(exc):
                raise
            return None

    async def send(self, chat_id, screen: Screen):
        if not self._theme.custom_emoji_enabled:
            screen = _plain_screen(screen)
        try:
            sent = await self._send_rich(chat_id, screen)
        except Exception as exc:
            if not _has_emoji(screen) or not _emoji_rejected(exc):
                raise
            self._theme.disable_custom_emoji()
            return await self.send(chat_id, _plain_screen(screen))
        if sent is not None:
            return sent
        text = rich_utils._classic_form(screen, screen.rich_text)
        try:
            return await self._post(chat_id, text, screen.keyboard)
        except Exception as exc:
            if not _has_emoji(screen) or not _emoji_rejected(exc):
                raise
            logger.warning("Custom emoji rejected (%s); retrying with unicode.", exc)
            self._theme.disable_custom_emoji()
            return await self._post(chat_id, strip_custom_emoji(text), _plain_screen(screen).keyboard)

    async def send_hero(self, chat_id, screen: Screen, photo: str | None):
        """Native rich image and card in one message, with explicit-only fallback.

        Wzgram binds uploaded/local/URL media to a tg://photo identifier. No
        custom network downloader or link-preview trick is involved.
        """
        if not self._theme.custom_emoji_enabled:
            screen = _plain_screen(screen)
        if photo and tables.rich_enabled() and rich_utils.available(self._client):
            try:
                return await self._client.send_rich_message(
                    chat_id=chat_id,
                    rich_text=InputRichMessage(
                        html='<img src="tg://photo?id=agent_hero" />' + screen.rich_text,
                        media=[InputRichMessageMedia(id="agent_hero", media=InputMediaPhoto(photo))],
                    ),
                    reply_markup=screen.keyboard,
                )
            except Exception as exc:
                if _has_emoji(screen) and _emoji_rejected(exc):
                    self._theme.disable_custom_emoji()
                    return await self.send_hero(chat_id, _plain_screen(screen), photo)
                if not rich_utils._refused(exc) and not _photo_rejected(exc):
                    raise
        return await self.send_photo(chat_id, screen, photo)

    async def send_photo(self, chat_id, screen: Screen, photo: str | None, *, caption_limit: int = 1024):
        """Send a screen as the caption of *photo*, falling back to plain text.

                Telegram caps captions at 1024 characters, and a picture that cannot be
                fetched must never cost the user the screen — both cases fall back to
                :meth:`send` instead of raising.
                
        """
        if not self._theme.custom_emoji_enabled:
            screen = _plain_screen(screen)
        text = to_safe_html(screen.rich_text)
        if not photo:
            return await self.send(chat_id, screen)
        if len(_visible_text(text).encode("utf-16-le")) // 2 > caption_limit:
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
            if _has_emoji(screen) and _emoji_rejected(exc):
                self._theme.disable_custom_emoji()
                return await self.send_photo(chat_id, _plain_screen(screen), photo, caption_limit=caption_limit)
            if not _photo_rejected(exc):
                raise
            logger.warning("Start image was rejected (%s); sending text instead.", type(exc).__name__)
            return await self.send(chat_id, screen)

    async def edit(self, callback_query, screen: Screen) -> bool | None:
        """Edit the message a callback query points at.

        True means confirmed; False means explicitly uneditable (safe to replace).
        None means unconfirmed or forbidden: callers must not resend the card.

        Rich first: the Bot API edits a rich message through
        ``edit_message_text(rich_message=…)``, so a table stays a table across a
        button press instead of collapsing into a monospace grid.
        """
        if not self._theme.custom_emoji_enabled:
            screen = _plain_screen(screen)
        client = getattr(callback_query, "_client", None) or self._client
        if (
            tables.rich_enabled()
            and rich_utils.needs_rich(screen.rich_text)
            and rich_utils.available(client)
        ):
            try:
                await callback_query.edit_message_text(
                    rich_text=InputRichMessage(html=screen.rich_text),
                    reply_markup=screen.keyboard,
                )
                return True
            except MessageNotModified:
                return True
            except Exception as exc:  # noqa: BLE001 - a refused edit is not fatal
                if _has_emoji(screen) and _emoji_rejected(exc):
                    self._theme.disable_custom_emoji()
                    return await self.edit(callback_query, _plain_screen(screen))
                if not rich_utils._refused(exc):
                    logger.warning("Screen edit failed (%s); no automatic retry.", type(exc).__name__)
                    return False if _uneditable(exc) else None
        text = rich_utils._classic_form(screen, screen.rich_text)
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
            if not _has_emoji(screen) or not _emoji_rejected(exc):
                logger.warning("Screen edit not confirmed (%s).", type(exc).__name__)
                return False if _uneditable(exc) else None
            logger.warning("Custom emoji rejected on edit (%s); retrying.", exc)
            self._theme.disable_custom_emoji()
            try:
                await callback_query.edit_message_text(
                    text=strip_custom_emoji(text),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_plain_screen(screen).keyboard,
                    link_preview_options=_no_preview(),
                )
                return True
            except Exception as exc:
                logger.warning("Screen edit retry not confirmed (%s).", type(exc).__name__)
                return False if _uneditable(exc) else None

    async def _post(self, chat_id, text: str, keyboard):
        return await self._client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options=_no_preview(),
        )
