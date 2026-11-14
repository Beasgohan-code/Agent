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

import re
from dataclasses import dataclass
from typing import Callable

from pyrogram.types import InlineKeyboardButton as Button
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


def welcome_screen(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
    """The first thing a user sees — and the caption of the /start picture.

    It has to survive the 1024-character caption cap and still say what the bot
    is, so it is three parts: a greeting, a small table of facts, and three
    commands worth trying. Nothing here is decoration that costs a line.
    """
    name = display_name(user)
    greeting = (
        f"{theme.emoji('wave')} Hello, <b>{rich_esc(name)}</b>!"
        if name
        else f"{theme.emoji('wave')} Hello!"
    )

    # No emoji inside a table: their rendered width is the client's choice, so a
    # glyph in a cell is what makes a monospace grid drift. Glyphs stay in the
    # prose around it.
    rows = [
        ("Version", __version__),
        ("Status", "online"),
        ("Privacy", "no message text stored"),
    ]
    if active:
        rows.insert(1, ("Commands", str(len(active))))
    table = kv_table(rows)

    text = (
        rich_heading("Agent", 2)
        + "\n"
        + greeting
        + "\n"
        + rich_note(
            f"{theme.emoji('sparkles')} One bot for files, moderation and music — "
            "one job queue, one store, one link signer underneath."
        )
        + "\n"
        # Classic grid on purpose: this screen is *edited* when the user taps a
        # button, and Telegram cannot edit a rich message.
        + table.classic_block()
        + "\n"
        + f"<b>{theme.emoji('bolt')} Try</b>"
        + "\n"
        + rich_list(
            [
                "<code>/help</code> — every command, one screen per section",
                "<code>/fsave</code> — reply to a file to keep it in your vault",
                "<code>/leech</code> — fetch a link and get the file back",
            ]
        )
        + "\n"
        + rich_hr()
        + rich_footer(
            f"{theme.emoji('bot')} wzgram + richgram · "
            "everything credited in <code>/about</code>"
        )
    )
    return Screen(text, keyboards.home_keyboard())


#: Command reference sections. Names come from the live registry, descriptions
#: from the same table the Telegram command menu uses, so ``/help`` and the menu
#: can never drift apart.
#: Registered outside the module registry, so the help filter must let them through.
BUILTIN = frozenset({"start", "help", "ping"})

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
        "box",
        "Vault & downloads",
        (
            "fsave", "get", "files", "del", "storestats", "storequota",
            "leech", "mirror", "tasklist", "taskstatus", "leechstats", "taskbackend",
        ),
    ),
    (
        "music",
        "Music (voice chat)",
        ("play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "leave"),
    ),
    (
        "lock",
        "Moderation",
        (
            "warn", "warnings", "unwarn", "mute", "unmute", "kick", "ban", "unban",
            "purge", "note", "trust", "antispam", "modlog", "warns",
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
        "fire",
        "Community & premium",
        (
            "report", "reports", "appeal",
            "post", "postpreview", "posttemplate", "verify",
            "premium", "addpremium", "delpremium", "premiumusers",
        ),
    ),
    (
        "bot",
        "Operations (owner)",
        ("restart", "watchdog", "plugins", "plugin", "events", "setlog", "unsetlog", "log"),
    ),
)


def section_slug(title: str) -> str:
    """``Vault & downloads`` -> ``vault-downloads``, for callback data."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def help_visible(commands, active: set[str] | None) -> list[str]:
    """The commands of a section that this deployment really registered."""
    return [
        name
        for name in commands
        if name and (active is None or name in active or name in BUILTIN)
    ]


def help_screen(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
    """The command reference, one section per button.

    *active* is the set of commands the registry actually registered. A plugin
    that could not start (music without a session string) must not appear in the
    reference — an entry for a command that does not exist is the same lie as a
    fake command — and with 79 commands the whole list no longer fits a message,
    so the overview stays short and each section has its own screen.
    """
    blocks = [
        rich_heading("Command reference", 2),
        rich_note(
            f"{theme.emoji('info')} Anything marked owner-only needs "
            "<code>OWNER_ID</code>; group commands need moderator rights."
        ),
    ]
    rows: list[tuple[str, str]] = []
    for icon, title, commands in HELP_SECTIONS:
        visible = help_visible(commands, active)
        if not visible:
            continue
        rows.append((f"{theme.emoji(icon)} {title}", str(len(visible))))
    if rows:
        blocks.append("")
        blocks.append(
            kv_table(rows, headers=("Section", "Commands")).classic_block()
        )
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            f"{theme.emoji('help')} Tap a section for what it does. "
            "Built on the projects credited in /about."
        )
    )
    return Screen("\n".join(blocks), _help_keyboard(active))


def _help_keyboard(active: set[str] | None) -> InlineKeyboardMarkup:
    rows: list[list[Button]] = []
    row: list[Button] = []
    for icon, title, commands in HELP_SECTIONS:
        if not help_visible(commands, active):
            continue
        row.append(Button(title, callback_data=f"help:{section_slug(title)}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Button("\u21a9\ufe0f Back to menu", callback_data=keyboards.CB_HOME)])
    return InlineKeyboardMarkup(rows)


def help_section_screen(title: str, user, theme: Theme, *, active: set[str] | None = None) -> Screen:
    """One section of the reference, with a sentence per command."""
    from ..platform.menu import DESCRIPTIONS

    if title is None:
        return help_screen(user, theme, active=active)
    icon, commands = "help", ()
    for section_icon, section_title, section_commands in HELP_SECTIONS:
        if section_title == title:
            icon, commands = section_icon, section_commands
            break
    lines = [
        f"<code>/{name}</code> — {rich_esc(DESCRIPTIONS[name])}"
        for name in help_visible(commands, active)
        if name in DESCRIPTIONS
    ]
    blocks = [
        rich_heading(f"{theme.emoji(icon)} {title}", 2),
        rich_list(lines) if lines else rich_note("Nothing in this section is available here."),
    ]
    return Screen("\n".join(blocks), _section_keyboard())


def _section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [Button("\u2b05\ufe0f All sections", callback_data=f"help:{ALL_SECTIONS}")],
            [Button("\u21a9\ufe0f Back to menu", callback_data=keyboards.CB_HOME)],
        ]
    )


def _section_builder(title: str):
    def build(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
        return help_section_screen(title, user, theme, active=active)

    return build


def info_screen(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
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
    return Screen(text, keyboards.info_keyboard(user_id if isinstance(user_id, int) else None))


# Callback data -> screen builder, used by the callback router.
SCREENS: dict[str, Callable[..., Screen]] = {
    keyboards.CB_HOME: welcome_screen,
    keyboards.CB_HELP: help_screen,
    keyboards.CB_INFO: info_screen,
}
#: Callback data that returns to the overview from a section screen.
ALL_SECTIONS = "all"
SCREENS[f"help:{ALL_SECTIONS}"] = help_screen
for _icon, _title, _commands in HELP_SECTIONS:
    SCREENS[f"help:{section_slug(_title)}"] = _section_builder(_title)


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
