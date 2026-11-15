"""Offline differential checks of the actual upstream /start handler AST.

Extract only the readable handler: do not import engine/config, start clients,
connect databases, decrypt credentials or load the PyArmor dependency.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from pyrogram.enums import ParseMode

ROOT = Path(__file__).resolve().parents[1]


def extract(source, name):
    node = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == name
    )
    node.decorator_list = []
    tree = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            node,
        ],
        type_ignores=[],
    )
    return compile(
        ast.fix_missing_locations(tree), "<isolated-upstream-handler>", "exec"
    )


async def run(source, case):
    settings = (
        {"custom_caption": "CUSTOM", "protect_content": True}
        if case == "delivery"
        else {}
    )
    if case == "custom_welcome":
        settings = {"start_message": "Owner text: {first}", "start_pic": "owner-photo"}
    doc = {"settings": settings}
    if case == "shortener":
        doc["shortener"] = {
            "enabled": True,
            "domain": "example.invalid",
            "api_key_encrypted": "test-only",
        }
    db = NS(
        present_user=AsyncMock(return_value=True),
        get_ban_users=AsyncMock(return_value=[22] if case == "banned" else []),
        set_verified=AsyncMock(),
        is_verified=AsyncMock(return_value=False),
        get_del_timer=AsyncMock(return_value=0),
    )
    main = NS(get_bot=AsyncMock(return_value=doc))
    message = NS(
        from_user=NS(
            id=22, mention="Alice", first_name="Alice", last_name="", username="alice"
        ),
        command=["start"],
        text="/start",
        reply=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    if case in ("delivery", "fetch_error", "shortener"):
        message.command.append("testpayload")
        message.text += " testpayload"
    if case == "verify":
        message.command.append("verify")
        message.text += " verify"
    file = NS(
        empty=False,
        caption=NS(html="original"),
        media=True,
        copy=AsyncMock(return_value=NS(id=100)),
    )
    client = NS(get_me=AsyncMock(return_value=NS(username="MeikoBot")))
    fetch = AsyncMock(return_value=[file])
    if case == "fetch_error":
        fetch.side_effect = RuntimeError("offline fixture error")
    env = dict(
        main_db=main,
        bot_id=7,
        bot_doc=doc,
        worker_db=db,
        log_channel_id=-100,
        check_force_sub=AsyncMock(return_value=case != "force_sub"),
        build_fsub_buttons=AsyncMock(return_value=None),
        decode=AsyncMock(return_value="get-1000"),
        is_admin=AsyncMock(return_value=False),
        get_messages=fetch,
        ParseMode=ParseMode,
        asyncio=asyncio,
        log=logging.getLogger("offline-worker-ui"),
    )
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    env.update(
        InlineKeyboardButton=InlineKeyboardButton,
        InlineKeyboardMarkup=InlineKeyboardMarkup,
    )
    caption = ModuleType("utils.caption_logic")
    caption.get_file_details = lambda msg: {"file_name": "fixture"}
    caption.format_caption = lambda template, details: "formatted"
    shortener = ModuleType("utils.shortener")
    shortener.shorten_url = AsyncMock(return_value="https://example.invalid/verify")
    with patch.dict(
        sys.modules,
        {
            "utils": ModuleType("utils"),
            "utils.caption_logic": caption,
            "utils.shortener": shortener,
        },
    ):
        exec(extract(source, "worker_start"), env)
        await env["worker_start"](client, message)
    if case == "delivery":
        file.copy.assert_awaited_once_with(
            chat_id=22,
            caption="original\n\nformatted",
            parse_mode=ParseMode.HTML,
            protect_content=True,
        )
    else:
        file.copy.assert_not_awaited()
    if case == "custom_welcome":
        message.reply_photo.assert_awaited_once_with(
            photo="owner-photo", caption="Owner text: Alice"
        )
    if case == "verify":
        db.set_verified.assert_awaited_once_with(22)
    return dict(
        copy=file.copy.await_args_list,
        fetch=[(call.args[1:], call.kwargs) for call in fetch.await_args_list],
        verified=db.set_verified.await_args_list,
        reply_count=message.reply.await_count,
        photo=message.reply_photo.await_args_list,
        decode=env["decode"].await_args_list,
        shortener=shortener.shorten_url.await_args_list,
    )


async def deletion(source, reload_url):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    messages = [NS(id=1, delete=AsyncMock()), NS(id=2, delete=AsyncMock())]
    notification = NS(edit=AsyncMock())
    sleep = AsyncMock()
    env = dict(
        asyncio=NS(sleep=sleep),
        log=logging.getLogger("offline-worker-ui"),
        InlineKeyboardButton=InlineKeyboardButton,
        InlineKeyboardMarkup=InlineKeyboardMarkup,
    )
    exec(extract(source, "_schedule_delete"), env)
    await env["_schedule_delete"](None, messages, notification, 30, reload_url)
    sleep.assert_awaited_once_with(30)
    for message in messages:
        message.delete.assert_awaited_once_with()
    keyboard = notification.edit.await_args.kwargs["reply_markup"]
    if reload_url:
        assert keyboard.inline_keyboard[0][0].url == reload_url
    else:
        assert keyboard is None
    return [
        message.delete.await_count for message in messages
    ], notification.edit.await_count


async def validate():
    original = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT / "Filestore"),
            "show",
            "010172404c2121862deea99f0fe25766d130e392:worker_bot/engine.py",
        ],
        text=True,
    )
    edited = (ROOT / "Filestore/worker_bot/engine.py").read_text()
    cases = (
        "banned",
        "force_sub",
        "verify",
        "delivery",
        "fetch_error",
        "shortener",
        "custom_welcome",
        "welcome",
    )
    for case in cases:
        assert await run(original, case) == await run(edited, case), case
    for url in (None, "https://t.me/MeikoBot?start=original_payload"):
        assert await deletion(original, url) == await deletion(edited, url)
    print(
        "2 scheduled-deletion comparisons passed: timer, deletes and original reload URL preserved."
    )
    print(
        f"{len(cases)} offline differential scenarios passed: ban, force-sub, verification, copying/caption/protection, fetch error, shortener gate, custom/default welcome."
    )


if __name__ == "__main__":
    asyncio.run(validate())
