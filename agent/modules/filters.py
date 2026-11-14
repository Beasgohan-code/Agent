"""Filters module — keyword auto-replies, from the filter plugins shared by
``CBML``/``WZML-X`` and ``Meikoagent``.

Command names follow Meikoagent's filter plugin (``filter``, ``filters``,
``stopfilter``); the storage is this repository's chat store rather than the
reference's database. A filter is a name plus a reply: when a message in the
group contains the name, the bot answers with the stored text.
"""

from __future__ import annotations

import html
import logging

from pyrogram import filters as tg_filters
from pyrogram.handlers import MessageHandler

from ..platform.manifest import PluginManifest

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="filters",
    name="Filters",
    version="1.0.0",
    description="Keyword auto-replies per group.",
    commands=("filter", "filters", "stopfilter"),
    permissions=("messages.read", "messages.send"),
    scope="group",
)

MAX_FILTER_NAME = 64


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


async def _is_manager(client, message, owner_id: int | None) -> bool:
    from .moderation import is_moderator

    return await is_moderator(client, message, need="can_change_info", owner_id=owner_id)


def watch(ctx):
    """Auto-reply when a message contains a stored filter name."""

    async def on_message(client, message):
        try:
            text = getattr(message, "text", "") or ""
            if not text or text.startswith("/"):
                return
            reply = ctx.chats.match_filter(message.chat.id, text)
            if reply is None:
                return
            await message.reply(reply)
        except Exception:  # noqa: BLE001 - watchers must never break the client
            logger.exception("filter watcher failed")

    return on_message


def extra_handlers(ctx):
    return [MessageHandler(watch(ctx), tg_filters.group)]


def build(ctx):
    async def _guard(client, message) -> bool:
        if await _is_manager(client, message, ctx.settings.owner_id):
            return True
        await message.reply("Only chat administrators can manage filters.")
        return False

    async def add(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        name = " ".join(args[1:2]).strip().lower()
        body = " ".join(args[2:]).strip()
        if not name or not body:
            await message.reply(
                "Usage: <code>/filter name reply text</code>\n"
                "Anyone saying the name in this group gets the reply."
            )
            return
        if len(name) > MAX_FILTER_NAME:
            await message.reply(f"Filter names are limited to {MAX_FILTER_NAME} characters.")
            return
        ctx.chats.set_filter(message.chat.id, name, body, by=message.from_user.id)
        await message.reply(f"Filter <code>{html.escape(name)}</code> saved.")

    async def listing(client, message):
        if not await _guard(client, message):
            return
        stored = ctx.chats.filters(message.chat.id)
        if not stored:
            await message.reply("This group has no filters yet.")
            return
        lines = ["<b>Filters</b>"]
        for name, reply in sorted(stored.items()):
            preview = reply if len(reply) <= 60 else reply[:57] + "…"
            lines.append(f"<code>{html.escape(name)}</code> → {html.escape(preview)}")
        await message.reply("\n".join(lines))

    async def stop(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        name = " ".join(args[1:2]).strip().lower()
        if not name:
            await message.reply("Usage: <code>/stopfilter name</code>")
            return
        if not ctx.chats.remove_filter(message.chat.id, name):
            await message.reply(f"No filter named <code>{html.escape(name)}</code>.")
            return
        await message.reply(f"Filter <code>{html.escape(name)}</code> removed.")

    return MANIFEST, {"filter": add, "filters": listing, "stopfilter": stop}
