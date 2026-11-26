"""Agent — the custom-emoji map, and the switch that turns it off.

Custom emoji are a cosmetic layer: every name here has a unicode fallback, so a
client or a deployment without them renders the plain glyph instead of a gap.
"""

from __future__ import annotations

import os

# IDs below are selected from the user-supplied @TgEmojis catalog.
# Existing speaker/unlock/bot entries have no equivalent in that catalog and
# retain their previous IDs. These are document identifiers, not live validation.
PREMIUM: dict[str, tuple[str, str]] = {
    "diamond": ("💎", "5042050649248760772"),
    "mic": ("🎤", "5039905162760553480"),
    "speaker": ("🔈", "5388632425314140043"),
    "sparkles": ("✨", "5040016479722931047"),
    "bolt": ("⚡", "5042334757040423886"),
    "check": ("✅", "5084979757905347540"),
    "cross": ("❌", "5040042498634810056"),
    "warn": ("⚠️", "5039665997506675838"),
    "ban": ("⛔", "5339233635620899144"),
    "lock": ("🔒", "5393302369024882368"),
    "unlock": ("🔓", "6037496202990194718"),
    "shield": ("🛡", "5042328396193864923"),
    "info": ("ℹ️", "5042306247047513767"),
    "globe": ("🌐", "5042186567783809934"),
    "stats": ("📊", "5042290883949495533"),
    "link": ("🔗", "5042101437237036298"),
    "search": ("🔍", "5039649904264217620"),
    "fire": ("🔥", "5039644681583985437"),
    "star": ("⭐️", "5042176294222037888"),
    "crown": ("👑", "5039727497143387500"),
    "bot": ("🤖", "6030400221232501136"),
    "music": ("🎵", "5334665104677941170"),
    "pin": ("📌", "5039600026809009149"),
    "eyes": ("👀", "5039623284056917259"),
    "gear": ("⚙️", "4904936030232117798"),
    "back": ("⬅️", "5875082500023258804"),
    "arrow": ("➡️", "5042341817966658405"),
    "key": ("🔧", "5258023599419171861"),
    "question": ("❓", "5042094496569885750"),
    "one": ("1️⃣", "5141109049114232089"),
    "two": ("2️⃣", "5140871649091912628"),
    "three": ("3️⃣", "5141399818400170896"),
    "download": ("📥", "5877307202888273539"),
    "copy": ("📄", "5877301185639091664"),
    "wave": ("👋", "5040033797031070992"),
    "rocket": ("✈️", "5875465628285931233"),
    "help": ("💡", "5042264341051605743"),
    "user": ("👤", "5771887475421090729"),
    "trash": ("🗑", "5879896690210639947"),
    "clock": ("⏰", "5123230779593196220"),
    "box": ("📦", "5924720918826848520"),
    "add": ("➕", "5039891861246838069"),
    "support": ("💬", "5040036030414062506"),
    "updates": ("📣", "5041888071851705019"),
    "home": ("🏡", "5042022053356504092"),
    "media": ("🎥", "5258217809250372293"),
    "folder": ("📁", "5875206779196935950"),
    "refresh": ("🔄", "5041837837914211014"),
}

# No supplied semantic match: leave these honestly Unicode-only.
PLAIN: dict[str, str] = {
    "id": "🆔",
    "hash": "#️⃣",
}


def premium_enabled() -> bool:
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
