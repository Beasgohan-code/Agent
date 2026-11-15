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
from ...platform.group_filters import operate, FilterError
from ...platform.admin_settings import denied
from ...ui.tables import Table, kv_table, panel
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

    return await is_moderator(client, message, need="can_change_info", owner_id=None)


def watch(ctx):
    """Auto-reply when a message contains a stored filter name."""

    async def on_message(client, message):
        try:
            text = getattr(message, "text", "") or ""
            if not text or text.startswith("/"):
                return
            stored = await operate(ctx, message.chat.id)
            matched = next((body for name, body in stored.items() if name and name in text.strip().lower()), None)
            if matched is None:
                return
            # Escaped on the way out: replies are sent with HTML parsing on, so an
            # unescaped tag would be injected into the group (or rejected).
            await reply(message, html.escape(matched))
        except Exception:  # noqa: BLE001 - watchers must never break the client
            logger.warning("filter reply unconfirmed")

    return on_message


def extra_handlers(ctx):
    return [MessageHandler(watch(ctx), tg_filters.group)]


def build(ctx):
    async def _guard(client, message) -> bool:
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            await reply(message, 'Use your personal Telegram user identity to manage filters.')
            return False
        if await _is_manager(client, message, ctx.settings.owner_id):
            return True
        await denied(ctx, message, "Only chat administrators can manage filters.")
        return False

    async def add(client, message):
        if not await _guard(client, message):
            return
        args = (getattr(message, 'text', '') or '').split(maxsplit=2)
        name = args[1].strip().lower() if len(args) > 1 else ''
        body = args[2].strip() if len(args) > 2 else ''
        if not name or not body:
            await reply(message, 
                "Usage: <code>/filter name reply text</code>\n"
                "Anyone saying the name in this group gets the reply."
            )
            return
        if len(name) > MAX_FILTER_NAME:
            await reply(message, f"Filter names are limited to {MAX_FILTER_NAME} characters.")
            return
        if len(body) > 2000:
            await reply(message, 'Filter replies are limited to 2000 characters; nothing was changed.')
            return
        stored = await operate(ctx, message.chat.id)
        if name not in stored and len(stored) >= 100:
            await reply(message, 'This group has 100 filters. Remove one before adding another; existing filters can still be updated.')
            return
        await operate(ctx, message.chat.id, name=name, body=body, actor=message.from_user.id)
        await reply(message, panel('Filter updated', icon=ctx.theme.emoji('check'),
            lines=[f"Filter <code>{html.escape(name)}</code> saved."],
            note='Saved. Configured PostgreSQL writes are committed before confirmation.', footer='/filters · /filters show name'))

    async def listing(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)[1:]
        stored = await operate(ctx, message.chat.id)
        usage = 'Use <code>/filters [page]</code> or <code>/filters show name</code>.'
        if args and args[0].lower() == 'show':
            if len(args) != 2:
                await reply(message, usage)
                return
            name = args[1].lower()
            if name not in stored:
                await reply(message, 'No filter with that name in this group.')
                return
            await reply(message, panel('Filter preview', icon=ctx.theme.emoji('eyes'),
                table=kv_table([('Trigger', name), ('Matching', 'substring, case-insensitive')]),
                lines=['<b>Stored reply</b>\n' + html.escape(stored[name])],
                note='Plain text reply. This preview is visible in the current chat.', footer='/stopfilter name · /filters'))
            return
        if len(args) > 1 or (args and (not args[0].isascii() or not args[0].isdecimal() or len(args[0]) > 8 or int(args[0]) < 1)):
            await reply(message, usage)
            return
        page = int(args[0]) if args else 1
        pages = max(1, (len(stored) + 9) // 10)
        if page > pages:
            await reply(message, f'Choose a filters page from 1 to {pages}.')
            return
        if not stored:
            await reply(message, 'This group has no filters yet.')
            return
        table = Table(headers=('Trigger', 'Reply'), rows=tuple(sorted(stored.items())[(page - 1) * 10:page * 10]))
        navigation = []
        if page > 1:
            navigation.append(f'<code>/filters {page - 1}</code> previous')
        if page < pages:
            navigation.append(f'<code>/filters {page + 1}</code> next')
        await reply(message, panel('Filters', icon=ctx.theme.emoji('search'),
            subtitle=f"{ctx.theme.emoji('diamond')} Page <b>{page}/{pages}</b> · {len(stored)} group filters",
            table=table, lines=[' · '.join(navigation)] if navigation else (),
            note='Full reply: <code>/filters show name</code>. Add: <code>/filter name reply text</code>.',
            footer='Case-insensitive substring matching · first stored match wins · responses visible in this chat'))

    async def stop(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        name = " ".join(args[1:2]).strip().lower()
        if len(args) != 2 or not name:
            await reply(message, "Usage: <code>/stopfilter name</code>")
            return
        if not await operate(ctx, message.chat.id, name=name, actor=message.from_user.id):
            await reply(message, f"No filter named <code>{html.escape(name)}</code>.")
            return
        await reply(message, f"Filter <code>{html.escape(name)}</code> removed.")

    def guarded(handler):
        async def call(client, message):
            try:
                await handler(client, message)
            except FilterError as error:
                await reply(message, str(error))
        return call

    return MANIFEST, {"filter": guarded(add), "filters": guarded(listing), "stopfilter": guarded(stop)}
