"""Offline dashboard behavior comparisons; no real workers, DB or transfers."""

import asyncio
import logging
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from validate_filestore_worker_ui import extract

ROOT = Path(__file__).resolve().parents[1]


async def scenario(source, name, allowed=False):
    db = NS(
        get_bot=AsyncMock(
            return_value={
                "_id": 7,
                "owner_id": 22 if allowed else 99,
                "settings": {},
                "bot_username": "fixture",
            }
        ),
        update_setting=AsyncMock(),
        delete_bot=AsyncMock(),
        purge_bot=AsyncMock(),
    )
    engine = NS(
        get_worker=Mock(return_value=None),
        start_worker=AsyncMock(),
        stop_worker=AsyncMock(),
    )
    query = NS(
        from_user=NS(id=22),
        data={
            "dashboard_callback": "dashboard_7",
            "toggle_bot_callback": "toggle_bot_7",
            "toggle_protect_callback": "toggle_protect_7",
            "toggle_permanent_link_callback": "toggle_permanent_link_7",
            "confirm_delete_callback": "confirm_delete_7",
            "delete_bot_callback": "delete_bot_7",
            "transfer_callback": "transfer_7",
            "do_transfer_callback": "dotransfer_7_8",
        }[name],
        answer=AsyncMock(),
        message=NS(edit_text=AsyncMock()),
    )
    creation = ModuleType("main_bot.plugins.create_bot")
    creation._creation_state = {22: {"step": "fixture"}}
    worker = ModuleType("worker_bot.engine")
    worker.worker_engine = engine
    env = dict(
        main_db=db,
        log=logging.getLogger("offline-dashboard"),
        InlineKeyboardButton=InlineKeyboardButton,
        InlineKeyboardMarkup=InlineKeyboardMarkup,
    )
    with patch.dict(
        sys.modules,
        {
            "main_bot": ModuleType("main_bot"),
            "main_bot.plugins": ModuleType("main_bot.plugins"),
            "main_bot.plugins.create_bot": creation,
            "worker_bot": ModuleType("worker_bot"),
            "worker_bot.engine": worker,
        },
    ):
        exec(extract(source, name), env)
        await env[name](None, query)
    db.update_setting.assert_not_awaited()
    db.delete_bot.assert_not_awaited()
    db.purge_bot.assert_not_awaited()
    engine.start_worker.assert_not_awaited()
    engine.stop_worker.assert_not_awaited()
    callbacks = []
    if allowed:
        query.message.edit_text.assert_awaited_once()
        keyboard = query.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [
            [button.callback_data for button in row] for row in keyboard.inline_keyboard
        ]
    else:
        query.message.edit_text.assert_not_awaited()
        query.answer.assert_awaited_once()
        assert query.answer.await_args.kwargs["show_alert"] is True
    return db.get_bot.await_args_list, callbacks, query.answer.await_count


async def validate():
    relative = "main_bot/plugins/my_bots.py"
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
    names = (
        "dashboard_callback",
        "toggle_bot_callback",
        "toggle_protect_callback",
        "toggle_permanent_link_callback",
        "confirm_delete_callback",
        "delete_bot_callback",
        "transfer_callback",
        "do_transfer_callback",
    )
    for name in names:
        assert await scenario(original, name) == await scenario(edited, name), name
    for name in ("dashboard_callback", "confirm_delete_callback"):
        assert await scenario(original, name, True) == await scenario(
            edited, name, True
        ), name
    print(
        "10 dashboard comparisons passed: eight ownership denials and authorized dashboard/delete-confirmation callback layouts; no destructive operations executed."
    )


if __name__ == "__main__":
    asyncio.run(validate())
