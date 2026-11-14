"""Agent — inline keyboards."""

from __future__ import annotations

from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

# Callback data is namespaced so future callbacks cannot collide.
CB_HOME = "menu:home"
CB_HELP = "menu:help"
CB_INFO = "menu:info"

SOURCE_URL = "https://github.com/Beasgohan-code/Agent"


def home_keyboard() -> Keyboard:
    return Keyboard(
        [
            [Button("\U0001f4a1 Help", callback_data=CB_HELP),
             Button("\U0001f464 My info", callback_data=CB_INFO)],
        ]
    )


def help_keyboard() -> Keyboard:
    return Keyboard(
        [
            [Button("\U0001f517 Source code", url=SOURCE_URL)],
            [Button("\u21a9\ufe0f Back to menu", callback_data=CB_HOME)],
        ]
    )


def info_keyboard() -> Keyboard:
    return Keyboard([[Button("\u21a9\ufe0f Back to menu", callback_data=CB_HOME)]])
