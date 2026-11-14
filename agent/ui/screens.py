"""Agent — screen builders.

Layout is composed from richgram's block builders plus the monospace tables in
:mod:`agent.ui.tables`. ``Screen.rich_text`` is rich markup; the sender converts
it to standard Telegram HTML and protects ``<pre>`` blocks while doing so.

Two rules keep the screens readable on a phone: prose stays in lists and
quotes, and anything with more than one column of data is a table. Command
references stay prose — a table would truncate the sentence that explains the
command, which is the whole point of ``/help``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pyrogram.types import InlineKeyboardMarkup
from richgram import (
    rich_esc,
    rich_footer,
    rich_heading,
    rich_hr,
    rich_list,
    rich_note,
)

from .. import __version__
from . import keyboards
from .tables import kv_table
from .theme import Theme


def format_uptime(seconds: float) -> str:
    """Human-readable uptime, e.g. ``2d 4h 11m``."""
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass(frozen=True)
class Screen:
    """A rendered screen: rich markup plus the keyboard shown under it."""

    rich_text: str
    keyboard: InlineKeyboardMarkup | None = None


def display_name(user) -> str:
    """Best-effort human name for a Telegram user."""
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    return " ".join(part for part in (first, last) if part)


def _username(user) -> str:
    username = (getattr(user, "username", None) or "").strip()
    return f"@{rich_esc(username)}" if username else "not set"


def welcome_screen(user, theme: Theme) -> Screen:
    name = display_name(user)
    greeting = (
        f"{theme.emoji('wave')} Hello, <b>{rich_esc(name)}</b>!" if name else f"{theme.emoji('wave')} Hello!"
    )

    # No emoji inside a table: their rendered width is the client's choice, so a
    # glyph in a cell is what makes a monospace grid drift. Glyphs stay in the
    # prose around it.
    table = kv_table(
        [
            ("Status", "online"),
            ("Version", __version__),
            ("Privacy", "no message text stored"),
        ]
    )
    text = (
        rich_heading("Agent", 2)
        + "\n"
        + greeting
        + "\n"
        + rich_note(
            f"{theme.emoji('sparkles')} Your always-on Telegram assistant. "
            "Use the buttons below to look around."
        )
        + "\n"
        # Classic grid on purpose: this screen is *edited* when the user taps a
        # button, and Telegram cannot edit a rich message.
        + table.classic_block()
        + "\n"
        + rich_hr()
        + rich_footer(
            f"{theme.emoji('bot')} Agent · wzgram + richgram · credits in /about"
        )
    )
    return Screen(text, keyboards.home_keyboard())


#: Command reference sections. Names come from the live registry, descriptions
#: from the same table the Telegram command menu uses, so ``/help`` and the menu
#: can never drift apart.
HELP_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "bolt",
        "Essentials",
        ("start", "help", "menu", "about", "status", "ping", "cancel", "owner", "id", "info", "time"),
    ),
    (
        "gear",
        "Encoding & files",
        (
            "encode", "encinfo", "encpreset", "enccancel",
            "autorename", "rename", "testrename", "clean",
            "genlink", "links", "revoke",
        ),
    ),
    (
        "lock",
        "Moderation",
        (
            "warn", "warnings", "unwarn", "mute", "unmute", "kick", "ban", "unban",
            "purge", "note", "trust", "antispam", "modlog",
        ),
    ),
    (
        "shield",
        "Group management",
        (
            "settings", "rules", "setrules", "pin", "unpin", "admins",
            "warnlimit", "resetwarns", "lockdown",
            "filter", "filters", "stopfilter",
            "setwelcome", "welcome", "goodbye",
        ),
    ),
    (
        "bot",
        "Operations (owner)",
        ("restart", "watchdog", "plugins", "plugin", "events", "setlog", "unsetlog", "log"),
    ),
)


def help_screen(user, theme: Theme) -> Screen:
    # Imported here so the UI layer keeps no import-time dependency on platform.
    from ..platform.menu import DESCRIPTIONS

    blocks = [
        rich_heading("Command reference", 2),
        rich_note(
            f"{theme.emoji('info')} Anything marked owner-only needs "
            "<code>OWNER_ID</code>; group commands need moderator rights."
        ),
    ]
    for icon, title, commands in HELP_SECTIONS:
        lines = [
            f"<code>/{name}</code> — {rich_esc(DESCRIPTIONS[name])}"
            for name in commands
            if name in DESCRIPTIONS
        ]
        if not lines:
            continue
        blocks.append("")
        blocks.append(rich_heading(f"{theme.emoji(icon)} {title}", 3))
        blocks.append(rich_list(lines))
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            f"{theme.emoji('help')} Built on the projects credited in /about — "
            "tap a button below to keep going."
        )
    )
    return Screen("\n".join(blocks), keyboards.help_keyboard())


def info_screen(user, theme: Theme) -> Screen:
    user_id = getattr(user, "id", None)
    language = (getattr(user, "language_code", None) or "").strip() or "not reported"
    premium = getattr(user, "is_premium", None)
    premium_text = "yes" if premium else ("no" if premium is False else "not reported")

    rows = [
        ("Name", rich_esc(display_name(user) or "not shared")),
        ("Username", _username(user)),
        (
            "User ID",
            f"<code>{int(user_id)}</code>" if isinstance(user_id, int) else "unknown",
        ),
        ("Language", rich_esc(language)),
        ("Premium", premium_text),
    ]

    text = (
        rich_heading("Your profile", 2)
        + "\n"
        + f"{theme.emoji('user')} This is what Telegram shares with the bot."
        + "\n"
        + kv_table(rows).classic_block()
        + "\n"
        + rich_hr()
        + rich_footer(f"{theme.emoji('id')} Nothing is stored — details are read live.")
    )
    return Screen(text, keyboards.info_keyboard())


# Callback data -> screen builder, used by the callback router.
SCREENS: dict[str, Callable[[object, Theme], Screen]] = {
    keyboards.CB_HOME: welcome_screen,
    keyboards.CB_HELP: help_screen,
    keyboards.CB_INFO: info_screen,
}


def ping_screen(monitor, theme: Theme) -> Screen:
    """Live health, as a Telegram reply (works on a Background Worker)."""
    if monitor is None:
        return Screen(
            rich_heading("Ping", 2)
            + "\n"
            + rich_note("Health tracking is not running."),
            keyboards.info_keyboard(),
        )

    snapshot = monitor.snapshot()
    rows = [
        ("State", snapshot.state),
        ("Uptime", format_uptime(snapshot.uptime_seconds)),
        (
            "Telegram latency",
            f"{snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "no probe yet",
        ),
        ("Probes", f"{snapshot.probes} ({snapshot.failures} failed)"),
    ]
    if snapshot.seconds_since_activity is not None:
        rows.append(("Last update", f"{format_uptime(snapshot.seconds_since_activity)} ago"))
    # The error goes below the table, not in it: a table cell is clipped to the
    # column width, and "ConnectionResetError: link dow…" is not a useful report.
    error_line = (
        f"Last error: <code>{rich_esc(snapshot.last_error[:200])}</code>"
        if snapshot.last_error
        else ""
    )

    text = (
        rich_heading("Ping", 2)
        + "\n"
        + f"{theme.emoji('bolt')} Live status of this instance."
        + "\n"
        + kv_table(rows).classic_block()
        + ("\n" + error_line if error_line else "")
        + "\n"
        + rich_hr()
        + rich_footer("The watchdog probes Telegram on a timer.")
    )
    return Screen(text, keyboards.info_keyboard())
