"""Agent — visual language shared by every screen."""

from __future__ import annotations

import re
from typing import Mapping

CUSTOM_EMOJI_RE = re.compile(
    r'<tg-emoji\s+emoji-id="[^"]*"\s*>(.*?)</tg-emoji>', re.IGNORECASE | re.DOTALL
)

# agent/ui/premium.py for packs and attribution). Inventing an id renders a
# broken glyph, so unknown names stay unicode.
from .premium import emoji_table

EMOJI_FALLBACKS, CUSTOM_EMOJI_IDS = emoji_table()


class Theme:
    """Renders UI glyphs, upgrading them to custom emoji when available."""

    def __init__(self, custom_emoji: Mapping[str, int] | None = None, *, worker_plugins=None) -> None:
        self.worker_plugins = None if worker_plugins is None else tuple(worker_plugins)
        source = emoji_table()[1] if custom_emoji is None else custom_emoji
        self._custom_emoji = {
            name: emoji_id
            for name, emoji_id in source.items()
            if name in EMOJI_FALLBACKS and emoji_id
        }

    def emoji_id(self, name: str) -> str | None:
        """Reviewed custom icon for Telegram buttons, respecting fallback mode."""
        value = self._custom_emoji.get(name)
        return str(value) if value else None

    def button(self, text: str, *, icon: str, callback_data=None, copy_text=None, style=None, disabled=False):
        """A native custom-emoji button with a readable Unicode fallback label."""
        from pyrogram.enums import ButtonStyle
        from pyrogram.types import InlineKeyboardButton
        glyph = EMOJI_FALLBACKS.get(icon, '')
        return InlineKeyboardButton(
            text=f'{glyph} {text}'.strip(), callback_data=callback_data, copy_text=copy_text,
            icon_custom_emoji_id=self.emoji_id(icon), disabled=disabled,
            style=ButtonStyle.DEFAULT if style is None else style,
        )

    @property
    def custom_emoji_enabled(self) -> bool:
        return bool(self._custom_emoji)

    def disable_custom_emoji(self) -> None:
        """Fall back to plain unicode for the rest of the process."""
        self._custom_emoji = {}

    def emoji(self, name: str) -> str:
        """Return the markup for *name* (custom emoji or unicode fallback)."""
        fallback = EMOJI_FALLBACKS.get(name, "")
        emoji_id = self._custom_emoji.get(name)
        if emoji_id:
            return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
        return fallback


def strip_custom_emoji(html_text: str) -> str:
    """Reduce custom emoji markup to the plain unicode character."""
    return CUSTOM_EMOJI_RE.sub(r"\1", html_text or "")


def panel_icon(title: str) -> str:
    """Stable feature accents using only the existing reviewed emoji catalog.

    Explicit caller icons are authoritative. No made-up document IDs, animations
    or semantic success claims are inferred from dynamic error/message bodies.
    """
    label = title.casefold()
    accents = (
        (("unconfirmed", "warning", "failed", "error", "denied"), "warn"),
        (("music", "playback", "playlist", "queue", "volume", "voice"), "music"),
        (("moderation", "blocklist", "flood", "protection", "approval"), "shield"),
        (("encoder", "encoding", "media", "rename", "compress"), "gear"),
        (("filestore", "vault", "files", "storage"), "lock"),
        (("linkshare", "link", "share", "leech", "transfer", "download"), "link"),
        (("post", "template", "greeting", "welcome", "goodbye"), "sparkles"),
        (("ai agent", "clone", "bot"), "bot"),
        (("premium", "plan"), "diamond"),
        (("group", "topic", "federation", "admin", "settings", "plugin"), "gear"),
    )
    key = next(
        (key for words, key in accents if any(word in label for word in words)), "info"
    )
    return Theme().emoji(key)
