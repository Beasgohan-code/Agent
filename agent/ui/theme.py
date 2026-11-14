"""Agent — visual language shared by every screen."""

from __future__ import annotations

import re
from typing import Mapping

CUSTOM_EMOJI_RE = re.compile(
    r'<tg-emoji\s+emoji-id="[^"]*"\s*>(.*?)</tg-emoji>', re.IGNORECASE | re.DOTALL
)

# Verified premium (custom) emoji IDs may be added here, e.g.
#   "sparkles": 1234567890123456789,
# No IDs are shipped because inventing one renders a broken glyph. Anything
# mapped here is upgraded to a custom emoji; everything else keeps the plain
# unicode fallback below and keeps working.
CUSTOM_EMOJI_IDS: dict[str, int] = {}

EMOJI_FALLBACKS: dict[str, str] = {
    "sparkles": "\u2728",
    "wave": "\U0001f44b",
    "rocket": "\U0001f680",
    "bolt": "\u26a1",
    "info": "\u2139\ufe0f",
    "help": "\U0001f4a1",
    "user": "\U0001f464",
    "id": "\U0001f194",
    "globe": "\U0001f310",
    "check": "\u2705",
    "back": "\u21a9\ufe0f",
    "bot": "\U0001f916",
}


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
