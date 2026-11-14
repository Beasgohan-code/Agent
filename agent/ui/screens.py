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
