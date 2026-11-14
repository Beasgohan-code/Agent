"""Agent — screen builders.

Layout is composed with richgram's block builders. ``Screen.rich_text`` is
rich markup; :mod:`agent.utils.sender` decides how it reaches Telegram and
always has a standard-HTML rendering available.
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
    rich_kv_table,
    rich_list,
    rich_note,
)

from . import keyboards
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
    greeting = f"{theme.emoji('wave')} Hello, <b>{rich_esc(name)}</b>!" if name else (
        f"{theme.emoji('wave')} Hello!"
    )

    text = (
        rich_heading("Agent", 2)
        + "\n"
        + greeting
        + "\n\n"
        + rich_note(
            f"{theme.emoji('sparkles')} Your always-on Telegram assistant. "
            "Use the buttons below to look around."
        )
        + "\n\n"
        + rich_kv_table(
            [
                ("Status", f"{theme.emoji('check')} Online"),
                ("Version", "Phase 1"),
            ]
        )
        + "\n"
        + rich_hr()
        + rich_footer(f"{theme.emoji('bot')} Agent · wzgram + richgram")
    )
    return Screen(text, keyboards.home_keyboard())


def help_screen(user, theme: Theme) -> Screen:
    text = (
        rich_heading("Help", 2)
        + "\n"
        + rich_list(
            [
                "<code>/start</code> — open the main menu",
                "<code>/help</code> — show this help",
                "<code>/menu</code> — open the menu · <code>/about</code> — what this is",
                "<code>/status</code> — live runtime status · <code>/cancel</code> — stop your jobs",
                "<code>/ping</code> — live health of this instance",
            ]
        )
        + "\n"
        + rich_list(
            [
                "<code>/encinfo</code> — probe a replied video",
                "<code>/encode</code> — encode it (fast · balanced · quality)",
                "<code>/encpreset</code> — list presets",
                "<code>/enccancel</code> — stop your jobs",
            ]
        )
        + "\n"
        + rich_list(
            [
                "<code>/genlink</code> — share a replied file",
                "<code>/links</code> — list your links",
                "<code>/revoke</code> — revoke one",
            ]
        )
        + "\n"
        + rich_list(
            [
                "<b>Group moderation</b>",
                "<code>/warn</code> <code>/warnings</code> <code>/unwarn</code> — warnings",
                "<code>/mute</code> <code>/unmute</code> <code>/kick</code> — restrict",
                "<code>/ban</code> <code>/unban</code> <code>/purge</code> — remove",
                "<code>/note</code> <code>/trust</code> — member metadata",
                "<code>/antispam</code> <code>/modlog</code> — policy and audit trail",
            ]
        )
        + "\n"
        + rich_note(
            f"{theme.emoji('info')} Phase 1 ships the core interface only. "
            "New abilities arrive in later phases."
        )
        + "\n"
        + rich_hr()
        + rich_footer("Tap a button below to keep going.")
    )
    return Screen(text, keyboards.help_keyboard())


def info_screen(user, theme: Theme) -> Screen:
    user_id = getattr(user, "id", None)
    language = (getattr(user, "language_code", None) or "").strip() or "not reported"
    premium = getattr(user, "is_premium", None)
    premium_text = "yes" if premium else ("no" if premium is False else "not reported")

    rows = [
        ("Name", rich_esc(display_name(user) or "not shared")),
        ("Username", _username(user)),
        ("User ID", f"<code>{int(user_id)}</code>" if isinstance(user_id, int) else "unknown"),
        ("Language", rich_esc(language)),
        ("Premium", premium_text),
    ]

    text = (
        rich_heading("Your profile", 2)
        + "\n"
        + f"{theme.emoji('user')} This is what Telegram shares with the bot."
        + "\n"
        + rich_kv_table(rows)
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
            rich_heading("Ping", 2) + "\n" + rich_note("Health tracking is not running."),
            keyboards.info_keyboard(),
        )

    snapshot = monitor.snapshot()
    rows = [
        ("State", f"{theme.emoji('check')} {snapshot.state}"),
        ("Uptime", format_uptime(snapshot.uptime_seconds)),
        ("Telegram latency", f"{snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "no probe yet"),
        ("Probes", f"{snapshot.probes} ({snapshot.failures} failed)"),
    ]
    if snapshot.seconds_since_activity is not None:
        rows.append(("Last update", f"{format_uptime(snapshot.seconds_since_activity)} ago"))
    if snapshot.last_error:
        rows.append(("Last error", rich_esc(snapshot.last_error)))

    text = (
        rich_heading("Ping", 2)
        + "\n"
        + f"{theme.emoji('bolt')} Live status of this instance."
        + "\n"
        + rich_kv_table(rows)
        + "\n"
        + rich_hr()
        + rich_footer("The watchdog probes Telegram on a timer.")
    )
    return Screen(text, keyboards.info_keyboard())
