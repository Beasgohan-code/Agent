"""Offline comparisons of readable creation handlers; no upstream imports."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from validate_filestore_worker_ui import extract

ROOT = Path(__file__).resolve().parents[1]


async def scenario(source, case):
    db = NS(
        count_user_bots=AsyncMock(return_value=3 if case == "limit" else 0),
        get_cooldown=AsyncMock(return_value=None),
        get_bot=AsyncMock(return_value=None),
    )
    state = {}
    if case != "entry" and case != "limit":
        state[22] = {"step": "awaiting_token", "data": {}}
    env = dict(
        main_db=db,
        _creation_state=state,
        MAX_BOTS_PER_USER=3,
        BOT_CREATION_COOLDOWN=60,
        datetime=datetime,
        timezone=timezone,
        InlineKeyboardButton=InlineKeyboardButton,
        InlineKeyboardMarkup=InlineKeyboardMarkup,
        validate_bot_token=AsyncMock(return_value=None),
    )
    query = NS(
        from_user=NS(id=22), answer=AsyncMock(), message=NS(edit_text=AsyncMock())
    )
    message = NS(
        from_user=NS(id=22),
        text=None if case == "nontext" else "invalid",
        reply=AsyncMock(),
    )
    name = (
        "create_bot_callback" if case in ("entry", "limit") else "handle_creation_input"
    )
    exec(extract(source, name), env)
    await env[name](None, query if name == "create_bot_callback" else message)
    if case == "entry":
        assert state == {22: {"step": "awaiting_token", "data": {}}}
        keyboard = query.message.edit_text.await_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].callback_data == "cancel_creation"
    elif case == "limit":
        assert query.answer.await_args.kwargs == {"show_alert": True}
        query.message.edit_text.assert_not_awaited()
        assert state == {}
    else:
        message.reply.assert_awaited_once()
        env["validate_bot_token"].assert_not_awaited()
        assert state[22]["step"] == "awaiting_token"
    return dict(
        state=state,
        count=db.count_user_bots.await_args_list,
        cooldown=db.get_cooldown.await_args_list,
        answered=query.answer.await_count,
        edited=query.message.edit_text.await_count,
        replied=message.reply.await_count,
    )


async def validate():
    relative = "main_bot/plugins/create_bot.py"
    original = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT / "Filestore"),
            "show",
            "010172404c2121862deea99f0fe25766d130e392:" + relative,
        ],
        text=True,
    )
    edited = (ROOT / "Filestore" / relative).read_text()
    for case in ("entry", "limit", "nontext", "invalid_token"):
        assert await scenario(original, case) == await scenario(edited, case), case
    print(
        "4 creation comparisons passed: entry state/cancel callback, bot-limit rejection, non-text rejection, malformed-token rejection."
    )


if __name__ == "__main__":
    asyncio.run(validate())
