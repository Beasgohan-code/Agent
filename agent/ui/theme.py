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

    def __init__(self, custom_emoji: Mapping[str, int] | None = None) -> None:
        source = CUSTOM_EMOJI_IDS if custom_emoji is None else custom_emoji
        self._custom_emoji = {
            name: emoji_id
            for name, emoji_id in source.items()
            if name in EMOJI_FALLBACKS and emoji_id
        }

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
