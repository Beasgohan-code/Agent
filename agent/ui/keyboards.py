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



def start_keyboard(bot_username=None) -> Keyboard:
    """Main-bot contact navigation; never used by worker overview screens."""
    import re
    rows = []
    if isinstance(bot_username, str) and re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot_username):
        rows.append([Button('➕ Add me', url=f'https://t.me/{bot_username}?startgroup=true', style=ButtonStyle.SUCCESS)])
    rows.extend([
        [Button('💡 Help', callback_data=CB_HELP, style=ButtonStyle.PRIMARY),
         Button('💬 Support', url='https://t.me/ouchro', style=ButtonStyle.PRIMARY)],
        [Button('📢 Updates', url='https://t.me/ouchro', style=ButtonStyle.SUCCESS),
         Button('👑 Owner', url='https://t.me/Godgohan')],
    ])
    return Keyboard(rows)


def home_keyboard(*, active=None) -> Keyboard:
    """The two things a new user actually wants."""
    rows = [[
        Button("✦ Explore commands", callback_data=CB_HELP, style=ButtonStyle.PRIMARY),
        Button("◉ My profile", callback_data=CB_INFO),
    ]]
    shortcuts = []
    if active is None or "warn" in active:
        shortcuts.append(Button("🛡 Group protection", callback_data="help:moderation", style=ButtonStyle.SUCCESS))
    if active is None or "get" in active:
        shortcuts.append(Button("🗂 Vault & downloads", callback_data="help:vault-downloads"))
    if shortcuts:
        rows.append(shortcuts)
    tools = []
    if active is None or "play" in active:
        tools.append(Button("♫ Music", callback_data="help:music-voice-chat", style=ButtonStyle.PRIMARY))
    if active is None or "encode" in active:
        tools.append(Button("🎞 Media studio", callback_data="help:encoding-files"))
    if tools:
        rows.append(tools)
    return Keyboard(rows)


def help_keyboard() -> Keyboard:
    return Keyboard(
        [
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
