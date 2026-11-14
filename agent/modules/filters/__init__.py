"""Filters — one keyword, one stored answer, per group.

``/filter <word> <reply>`` stores the reply, ``/filters`` lists what is stored
and ``/stopfilter`` removes one. The watcher that answers with them lives in
this module, so a stored filter is never decoration.
"""

from __future__ import annotations

import html
import logging

from pyrogram import filters as tg_filters
from pyrogram.handlers import MessageHandler

from ...platform.manifest import PluginManifest
from ...ui.tables import Table, panel
from ...utils.rich import reply

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
    from ..moderation import is_moderator

    return await is_moderator(client, message, need="can_change_info", owner_id=owner_id)


def watch(ctx):
    """Auto-reply when a message contains a stored filter name."""

    async def on_message(client, message):
        try:
            text = getattr(message, "text", "") or ""
            if not text or text.startswith("/"):
                return
            matched = ctx.chats.match_filter(message.chat.id, text)
            if matched is None:
                return
            # Escaped on the way out: replies are sent with HTML parsing on, so an
            # unescaped tag would be injected into the group (or rejected).
            await reply(message, html.escape(matched))
        except Exception:  # noqa: BLE001 - watchers must never break the client
            logger.exception("filter watcher failed")

    return on_message


def extra_handlers(ctx):
    return [MessageHandler(watch(ctx), tg_filters.group)]


def build(ctx):
    async def _guard(client, message) -> bool:
        if await _is_manager(client, message, ctx.settings.owner_id):
            return True
        await reply(message, "Only chat administrators can manage filters.")
        return False

    async def add(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        name = " ".join(args[1:2]).strip().lower()
        body = " ".join(args[2:]).strip()
        if not name or not body:
            await reply(message, 
                "Usage: <code>/filter name reply text</code>\n"
                "Anyone saying the name in this group gets the reply."
            )
            return
        if len(name) > MAX_FILTER_NAME:
            await reply(message, f"Filter names are limited to {MAX_FILTER_NAME} characters.")
            return
        ctx.chats.set_filter(message.chat.id, name, body, by=message.from_user.id)
        await reply(message, f"Filter <code>{html.escape(name)}</code> saved.")

    async def listing(client, message):
        if not await _guard(client, message):
            return
        stored = ctx.chats.filters(message.chat.id)
        if not stored:
            await reply(message, "This group has no filters yet.")
            return
        table = Table(
            headers=("Trigger", "Reply"),
            rows=tuple(
                (name, reply) for name, reply in sorted(stored.items())
            ),
        )
        await reply(message, 
            panel(
                "Filters",
                icon=ctx.theme.emoji("search"),
                subtitle=(
                    f"<b>{len(stored)}</b> keyword "
                    f"auto-repl{'y' if len(stored) == 1 else 'ies'} in this group."
                ),
                table=table,
                note="Add with <code>/filter name reply text</code>, remove with <code>/stopfilter name</code>.",
                footer="Replies are stored per group and sent verbatim.",
            )
        )

    async def stop(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        name = " ".join(args[1:2]).strip().lower()
        if not name:
            await reply(message, "Usage: <code>/stopfilter name</code>")
            return
        if not ctx.chats.remove_filter(message.chat.id, name):
            await reply(message, f"No filter named <code>{html.escape(name)}</code>.")
            return
        await reply(message, f"Filter <code>{html.escape(name)}</code> removed.")

    return MANIFEST, {"filter": add, "filters": listing, "stopfilter": stop}
