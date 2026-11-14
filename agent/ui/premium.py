"""Premium (custom) emoji.

The IDs below are **real**, taken from ``Beasgohan-code/Videl0``'s curated map
(``videl/utils/premium_emojis.py``), which documents the four packs they come
from: NewsEmoji, Telegram iOS Icons, @rijif and SoLo_HaMiD. Nothing here is
invented — a fabricated ID renders a broken glyph, which is worse than a
unicode one.

Videl0's own comment applies unchanged: *IDs alone do not grant Premium
rendering*. A bot may be refused, so :mod:`agent.utils.sender` retries once with
plain unicode, and ``USE_PREMIUM_EMOJI=0`` turns the whole layer off.
"""

from __future__ import annotations

import os

#: name -> (unicode fallback, custom emoji id)  — ids from Videl0's packs.
PREMIUM: dict[str, tuple[str, str]] = {
    "sparkles": ("\u2728", "5325547803936572038"),      # ✨ NewsEmoji
    "bolt": ("\u26a1", "5042334757040423886"),          # ⚡ @rijif
    "check": ("\u2705", "5084979757905347540"),         # ✅ SoLo
    "cross": ("\u274c", "5210952531676504517"),         # ❌ NewsEmoji
    "warn": ("\u26a0\ufe0f", "5447644880824181073"),    # ⚠️ NewsEmoji
    "ban": ("\u26d4\ufe0f", "5260293700088511294"),     # ⛔️ NewsEmoji
    "lock": ("\U0001f512", "5296369303661067030"),      # 🔒 NewsEmoji
    "unlock": ("\U0001f513", "6037496202990194718"),    # 🔓 tgiosicons
    "shield": ("\U0001f6e1", "6030445631921721471"),    # 🛡 tgiosicons
    "info": ("\u2139\ufe0f", "5334544901428229844"),    # ℹ️ NewsEmoji
    "globe": ("\U0001f310", "5447410659077661506"),     # 🌐 NewsEmoji
    "stats": ("\U0001f4ca", "5231200819986047254"),     # 📊 NewsEmoji
    "link": ("\U0001f517", "5271604874419647061"),      # 🔗 NewsEmoji
    "search": ("\U0001f50d", "5231012545799666522"),    # 🔍 NewsEmoji
    "fire": ("\U0001f525", "5424972470023104089"),      # 🔥 NewsEmoji
    "star": ("\u2b50\ufe0f", "5438496463044752972"),    # ⭐️ NewsEmoji
    "crown": ("\U0001f451", "5217822164362739968"),     # 👑 NewsEmoji
    "bot": ("\U0001f916", "6030400221232501136"),       # 🤖 tgiosicons
    "music": ("\U0001f3b5", "5463107823946717464"),     # 🎵 NewsEmoji
    "pin": ("\U0001f4cc", "5397782960512444700"),       # 📌 NewsEmoji
    "eyes": ("\U0001f440", "5039623284056917259"),      # 👀 @rijif
    "gear": ("\u2699\ufe0f", "5341715473882955310"),    # ⚙️ NewsEmoji
    "back": ("\u21a9\ufe0f", "5960671702059848143"),    # ⬅️ tgiosicons
    "arrow": ("\u27a1\ufe0f", "5416117059207572332"),   # ➡️ NewsEmoji
    "question": ("\u2753", "5436113877181941026"),      # ❓ NewsEmoji
    "key": ("\U0001f527", "5962952497197748583"),       # 🔧 tgiosicons
    "one": ("1\ufe0f\u20e3", "5141109049114232089"),
    "two": ("2\ufe0f\u20e3", "5140871649091912628"),
    "three": ("3\ufe0f\u20e3", "5141399818400170896"),
}

#: Glyphs with no vetted id stay unicode: better plain than broken.
PLAIN: dict[str, str] = {
    "wave": "\U0001f44b",
    "rocket": "\U0001f680",
    "help": "\U0001f4a1",
    "user": "\U0001f464",
    "id": "\U0001f194",
    "trash": "\U0001f5d1",
    "clock": "\U0001f552",
    "hash": "#\ufe0f\u20e3",
}


def premium_enabled() -> bool:
    """``USE_PREMIUM_EMOJI=0`` disables the layer, matching Videl0."""
    raw = os.getenv("USE_PREMIUM_EMOJI", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def emoji_table() -> tuple[dict[str, str], dict[str, int]]:
    """(fallbacks, ids) for :class:`agent.ui.theme.Theme`."""
    fallbacks = dict(PLAIN)
    ids: dict[str, int] = {}
    enabled = premium_enabled()
    for name, (glyph, emoji_id) in PREMIUM.items():
        fallbacks[name] = glyph
        if enabled:
            ids[name] = int(emoji_id)
    return fallbacks, ids
