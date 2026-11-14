"""Agent — inline keyboards.

Button *styles* are the Bot API 10.3 addition this module exists to use: a
coloured button says what it does before the label is read (primary = the thing
to do next, success = safe, danger = destructive). Older clients ignore the
field, so nothing breaks where it is unsupported.

``copy_text`` is the other new one: the info screen can hand over a user id
without the user selecting text on a phone.
"""

from __future__ import annotations

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

# Callback data is namespaced so future callbacks cannot collide.
CB_HOME = "menu:home"
CB_HELP = "menu:help"
CB_INFO = "menu:info"

SOURCE_URL = "https://github.com/Beasgohan-code/Agent"


def home_keyboard() -> Keyboard:
    """The two things a new user actually wants."""
    return Keyboard(
        [
            [
                Button("\U0001f4a1 Help", callback_data=CB_HELP, style=ButtonStyle.PRIMARY),
                Button("\U0001f464 My info", callback_data=CB_INFO),
            ],
            [Button("\U0001f517 Source", url=SOURCE_URL)],
        ]
    )


def help_keyboard() -> Keyboard:
    return Keyboard(
        [
            [Button("\U0001f517 Source code", url=SOURCE_URL)],
            [Button("\u21a9\ufe0f Back to menu", callback_data=CB_HOME, style=ButtonStyle.PRIMARY)],
        ]
    )


def nav_keyboard() -> Keyboard:
    """One row for a panel that is not the menu: the two ways back.

        A panel answers a question ("what is my tier?", "is it healthy?") and then
        leaves the user on a dead end; this is the second half of that sentence.
        
    """
    return Keyboard(
        [
            [
                Button("\U0001f3e0 Menu", callback_data=CB_HOME, style=ButtonStyle.PRIMARY),
                Button("\U0001f4a1 Help", callback_data=CB_HELP),
            ]
        ]
    )


def info_keyboard(user_id: int | None = None) -> Keyboard:
    """Includes a copy button when the id is known, so it can be pasted."""
    rows = []
    if isinstance(user_id, int):
        rows.append(
            [
                Button(
                    "\U0001f4cb Copy my id",
                    copy_text=str(user_id),
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    rows.append(
        [Button("\u21a9\ufe0f Back to menu", callback_data=CB_HOME, style=ButtonStyle.PRIMARY)]
    )
    return Keyboard(rows)
