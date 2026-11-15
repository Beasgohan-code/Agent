"""Leech entry screens; only installed, implemented transfer paths are offered."""

import logging

from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    InlineKeyboardButton as Button,
    InlineKeyboardMarkup as Keyboard,
)
from ...ui.tables import panel, kv_table
from ...utils.rich import reply, edit

logger = logging.getLogger(__name__)


def screen(ctx, view="home", user_id=None):
    if view == "uploads":
        from ...platform.attachments import CAPTION_KEY, THUMB_KEY

        chats, db = getattr(ctx, "chats", None), getattr(ctx, "db", None)
        ready = chats is not None and (db is None or db.connected)
        caption = chats.get(user_id, CAPTION_KEY) if ready else None
        thumb = chats.get(user_id, THUMB_KEY) if ready else None
        body = panel(
            "Personal upload settings",
            icon=ctx.theme.emoji("gear"),
            table=kv_table(
                [
                    ("Storage", "available" if ready else "unavailable"),
                    (
                        "Caption",
                        ("configured" if caption else "default")
                        if ready
                        else "unknown",
                    ),
                    (
                        "Thumbnail",
                        ("configured" if thumb else "default") if ready else "unknown",
                    ),
                ]
            ),
            lines=[
                "<code>/set_caption File: {filename} · {size}</code>",
                "<code>/see_caption</code> · <code>/del_caption</code>",
                "Reply to a photo with <code>/set_thumb</code>.",
                "<code>/view_thumb</code> · <code>/del_thumb</code>",
            ],
            note="These shared settings apply to files delivered in your private chat by this bot. Status may reflect cached state; a failed database flush is not proof of persistence.",
        )
    elif view == "backends":
        from . import backends

        body = panel(
            "Leech availability",
            icon=ctx.theme.emoji("gear"),
            table=kv_table(
                [
                    (
                        label,
                        "available"
                        if label in ("local", "TypeTube") and available == "yes"
                        else "installed; not integrated"
                        if available == "yes"
                        else "not installed",
                    )
                    for label, available, _ in backends()
                ]
            ),
            note="Only direct public HTTP(S) downloads and TypeTube YouTube audio are currently integrated. Installed binaries are not proof of a working backend.",
        )
    elif view == "help":
        body = panel(
            "Start a transfer",
            icon=ctx.theme.emoji("info"),
            lines=[
                "<code>/leech https://example.com/file.zip</code>",
                '<code>/leech https://example.com/file.zip -n "My file.zip"</code>',
                "Or reply to one public file URL with <code>/leech</code>.",
                "<code>/mirror URL</code> retains an owned copy in this bot’s storage.",
                "<code>/cancel</code> stops your active job.",
            ],
            note="YouTube video links download audio through TypeTube’s public cluster. Other webpage links, torrents, login-required pages and remote-drive uploads are not implemented. Never submit private credentials or secret links.",
        )
    else:
        body = panel(
            "Meiko · Leech",
            icon=ctx.theme.emoji("gear"),
            lines=[
                "Download a public HTTP(S) file and receive it here as a Telegram document.",
                "Usage: <code>/leech URL</code>, or reply to one file URL with <code>/leech</code>.",
            ],
            note="Direct files and YouTube audio (TypeTube public cluster). Group use requires Owner approval and admin activation; private use requires the plugin runtime to be enabled.",
            footer="/set_caption · /see_caption · /del_caption",
        )
    return body, Keyboard(
        [
            [
                Button("How to transfer", callback_data="leech:help"),
                Button("Availability", callback_data="leech:backends"),
            ],
            [Button("Upload settings", callback_data="leech:uploads")],
            [Button("Leech home", callback_data="leech:home")],
        ]
    )


def build(ctx):
    async def press(client, query, rest):
        if rest not in ("home", "help", "backends", "uploads"):
            await query.answer("Unknown Leech screen.", show_alert=True)
            return
        uid = getattr(getattr(query, "from_user", None), "id", None)
        if rest == "uploads" and (
            type(uid) is not int
            or uid <= 0
            or getattr(query.message.chat, "id", None) != uid
        ):
            await query.answer(
                "Open /leech privately to view personal upload settings.",
                show_alert=True,
            )
            return
        body, keyboard = screen(ctx, rest, user_id=uid)
        try:
            await edit(query, body, reply_markup=keyboard)
        except MessageNotModified:
            pass
        except Exception:
            logger.warning("Leech screen update failed; reopen required")
            await query.answer(
                "This screen could not be updated. Send /leech to reopen it.",
                show_alert=True,
            )
            return
        await query.answer()

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles("leech:home"):
        router.register("leech", press)

    async def show(message):
        body, keyboard = screen(ctx)
        await reply(message, body, reply_markup=keyboard)

    return show
