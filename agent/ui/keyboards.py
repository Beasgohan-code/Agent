"""Agent — inline keyboards.

Button *styles* are the Bot API 10.3 addition this module exists to use: a
coloured button says what it does before the label is read (primary = the thing
to do next, success = safe, danger = destructive). Older clients ignore the
field, so nothing breaks where it is unsupported.

``copy_text`` is the other new one: the info screen can hand over a user id
without the user selecting text on a phone.
"""

from __future__ import annotations

from .theme import Theme
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardMarkup as Keyboard

# Callback data is namespaced so future callbacks cannot collide.
CB_HOME = "menu:home"
CB_HELP = "menu:help"
CB_INFO = "menu:info"



def start_keyboard(bot_username=None, *, theme=None) -> Keyboard:
    """Main-bot contact navigation; never used by worker overview screens."""
    import re
    theme = theme or Theme()
    rows = []
    if isinstance(bot_username, str) and re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot_username):
        rows.append([theme.button('Add me', icon='add', url=f'https://t.me/{bot_username}?startgroup=true', style=ButtonStyle.SUCCESS)])
    rows.extend([
        [theme.button('Help', icon='help', callback_data=CB_HELP, style=ButtonStyle.PRIMARY),
         theme.button('Support', icon='support', url='https://t.me/ouchro', style=ButtonStyle.PRIMARY)],
        [theme.button('Updates', icon='updates', url='https://t.me/ouchro', style=ButtonStyle.SUCCESS),
         theme.button('Owner', icon='crown', url='https://t.me/Godgohan')],
    ])
    return Keyboard(rows)


def home_keyboard(*, active=None, theme=None) -> Keyboard:
    """The two things a new user actually wants."""
    theme = theme or Theme()
    rows = [[
        theme.button("Explore commands", icon="sparkles", callback_data=CB_HELP, style=ButtonStyle.PRIMARY),
        theme.button("My profile", icon="user", callback_data=CB_INFO),
    ]]
    shortcuts = []
    if active is None or "warn" in active:
        shortcuts.append(theme.button("Group protection", icon="shield", callback_data="help:moderation", style=ButtonStyle.SUCCESS))
    if active is None or "get" in active:
        shortcuts.append(theme.button("Vault & downloads", icon="folder", callback_data="help:vault-downloads"))
    if shortcuts:
        rows.append(shortcuts)
    tools = []
    if active is None or "play" in active:
        tools.append(theme.button("Music", icon="music", callback_data="help:music-voice-chat", style=ButtonStyle.PRIMARY))
    if active is None or "encode" in active:
        tools.append(theme.button("Media studio", icon="media", callback_data="help:encoding-files"))
    if tools:
        rows.append(tools)
    return Keyboard(rows)


def help_keyboard(*, theme=None) -> Keyboard:
    theme = theme or Theme()
    return Keyboard(
        [
            [theme.button("Back to menu", icon="back", callback_data=CB_HOME, style=ButtonStyle.PRIMARY)],
        ]
    )


def nav_keyboard(*, theme=None) -> Keyboard:
    """One row for a panel that is not the menu: the two ways back.

        A panel answers a question ("what is my tier?", "is it healthy?") and then
        leaves the user on a dead end; this is the second half of that sentence.
        
    """
    theme = theme or Theme()
    return Keyboard(
        [
            [
                theme.button("Menu", icon="home", callback_data=CB_HOME, style=ButtonStyle.PRIMARY),
                theme.button("Help", icon="help", callback_data=CB_HELP),
            ]
        ]
    )


def info_keyboard(user_id: int | None = None, *, theme=None) -> Keyboard:
    """Includes a copy button when the id is known, so it can be pasted."""
    theme = theme or Theme()
    rows = []
    if isinstance(user_id, int):
        rows.append(
            [
                theme.button(
                    "Copy my id", icon="copy",
                    copy_text=str(user_id),
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
    rows.append(
        [theme.button("Back to menu", icon="back", callback_data=CB_HOME, style=ButtonStyle.PRIMARY)]
    )
    return Keyboard(rows)
