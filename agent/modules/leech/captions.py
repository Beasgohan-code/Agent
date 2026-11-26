"""Saver caption commands adapted to Meiko's shared attachment pipeline.

Workflow source: abhinai2244/save-restricted-content-bot, cantarella/caption.py,
revision bf2e45a1ef187060e053e59c0336cb0e6a4a022b.
Copyright (c) 2026 LastPerson07. MIT notice: licenses/saver-MIT.txt.
No upstream client, database or credential configuration is imported.
"""

import html

from ...platform.attachments import CAPTION_KEY, MAX_CAPTION
from ...utils.rich import reply
from ..filestore.channel_links import private


def build(ctx):
    async def handle(message, action):
        if not private(message):
            await reply(
                message,
                "Use your personal Telegram identity in private chat to manage upload captions.",
            )
            return
        chats = getattr(ctx, "chats", None)
        db = getattr(ctx, "db", None)
        if chats is None or (db is not None and not db.connected):
            await reply(message, "Caption storage is unavailable. No change confirmed.")
            return
        uid = message.from_user.id
        current = chats.get(uid, CAPTION_KEY)
        if action == "see":
            await reply(
                message,
                "Your caption:\n<code>" + html.escape(current) + "</code>"
                if current
                else "No personal caption set. Use /set_caption with {filename} and {size}.",
            )
            return
        if action == "set":
            parts = (getattr(message, "text", "") or "").split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                await reply(message, "Usage: /set_caption File: {filename} · {size}")
                return
            value = parts[1].strip()
            if len(value.encode("utf-16-le")) // 2 > MAX_CAPTION:
                await reply(message, f"Caption must fit {MAX_CAPTION} UTF-16 units.")
                return
        else:
            value = None
            if not current:
                await reply(message, "No personal caption is set.")
                return
        try:
            chats.put(uid, CAPTION_KEY, value)
            if db is not None:
                if await db.flush() <= 0:
                    raise RuntimeError("Caption persistence unconfirmed")
        except Exception:
            await reply(
                message,
                "Caption persistence was not confirmed. The current view may be cached; retry when storage is available.",
            )
            return
        await reply(
            message,
            "Personal caption saved. It applies to files delivered in this private chat."
            if value
            else "Personal caption removed. Default captions will be used.",
        )

    async def set_caption(client, message):
        await handle(message, "set")

    async def see_caption(client, message):
        await handle(message, "see")

    async def del_caption(client, message):
        await handle(message, "delete")

    return {
        "set_caption": set_caption,
        "see_caption": see_caption,
        "del_caption": del_caption,
    }
