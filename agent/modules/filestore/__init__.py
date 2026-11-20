"""FileStore archive-channel links and delivery.

The channel workflow copies Telegram messages without downloading them.
Legacy owned-file retrieval and replied batch saving remain for compatibility;
their download limits do not apply to archive-channel delivery.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ...platform.attachments import attachment_kwargs
from ...platform.manifest import PluginManifest
from ...ui.tables import Table, kv_table, panel
from ...utils.delivery import send_stored
from ...utils.rich import reply
from .channel_links import build as build_channel_links
from .vault import (
    MAX_BATCH,
    MAX_BOT_DOWNLOAD,
    _args,
    human_bytes,
    media_in,
    media_name,
    media_size,
)

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=True,
    slug="filestore",
    name="Filestore",
    version="1.0.0",
    description="Archive-channel range links and private redemption; legacy owned-file retrieval retained.",
    commands=("get", "batch", "custom_batch"),
    permissions=("messages.read", "messages.send", "storage.read", "storage.write"),
    scope="all",
)

#: Telegram's Bot API download cap for bots, in bytes.


def build(ctx):
    storage = ctx.storage
    channel_commands = build_channel_links(ctx)
    from .conversation import ArchiveConversation
    conversation = ArchiveConversation(ctx, channel_commands["custom_batch"])
    ctx._filestore_conversation = conversation
    original_generate = channel_commands["custom_batch"]

    async def custom_batch(client, message):
        if len(_args(message)) == 1 and not getattr(message, "reply_to_message", None):
            await conversation.start(client, message, "custom_batch")
            return
        await original_generate(client, message)

    channel_commands["custom_batch"] = custom_batch


    def _tier_label(owner_id: int) -> str:
        book = getattr(ctx, "premium", None)
        return book.tier(owner_id).label if book is not None else "deployment default"

    def allowance(owner_id: int) -> int:
        """The caller's vault size, which depends on their tier."""
        book = getattr(ctx, "premium", None)
        return book.tier(owner_id).quota_bytes if book is not None else storage.quota_bytes

    def _quota_rows(owner_id: int) -> list[tuple[str, str]]:
        used = storage.usage(owner_id)
        quota = allowance(owner_id)
        return [
            ("Files", str(len(storage.list_owned(owner_id)))),
            ("Used", human_bytes(used)),
            ("Quota", human_bytes(quota)),
            ("Free", human_bytes(max(0, quota - used))),
        ]



    # -- /get --------------------------------------------------------------

    async def get(client, message):
        args = _args(message)
        if len(args) != 2:
            await reply(message, 
                "Usage: <code>/get &lt;id&gt;</code> — use the ID returned by a successful save."
            )
            return
        file_id = args[1].strip()
        stored = storage.get(file_id)
        if stored is None or stored.owner_id != message.from_user.id:
            await reply(message, "That id is not in your vault.")
            return
        # One delivery path for every store: cached file_id first, then the disk,
        # then an honest "the bytes are gone". See agent.utils.delivery.
        await send_stored(
            message,
            storage,
            stored,
            **attachment_kwargs(
                ctx.chats,
                message.chat.id,
                name=stored.name,
                size=human_bytes(stored.size),
            ),
        )

    # -- /batch ------------------------------------------------------------

    async def batch(client, message):
        """Save a run of consecutive files, starting at the replied one."""
        parts = _args(message)
        from .channel_links import private
        if len(parts) == 1 and private(message) and not getattr(message, "reply_to_message", None):
            await conversation.start(client, message, "batch")
            return
        # New archive-range syntax is private and separate from legacy replied
        # media batches. Keep old stored-file workflows and links intact.
        from .channel_links import private
        if len(parts) == 3 and private(message):
            await channel_commands["custom_batch"](client, message)
            return
        if len(parts) > 2 or (len(parts) == 2 and (not parts[1].isascii() or not parts[1].isdecimal()
                or len(parts[1]) > 2 or not 1 <= int(parts[1]) <= MAX_BATCH)):
            await reply(message, f"Usage: <code>/batch [count]</code> — choose 1–{MAX_BATCH} and reply to the first file.")
            return
        count = int(parts[1]) if len(parts) > 1 else 10
        replied = getattr(message, "reply_to_message", None)
        start = getattr(replied, "id", None)
        if start is None:
            await reply(
                message,
                "Reply to the first file of the batch, then <code>/batch "
                f"{count}</code> saves it and the next {count - 1} messages.",
            )
            return
        ids = [start + offset for offset in range(count)]
        try:
            messages = await client.get_messages(message.chat.id, message_ids=ids)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            await reply(message, f"Could not read those messages ({type(exc).__name__}). Check access and retry.")
            return
        saved: list = []
        skipped = failed = 0
        total = 0
        for item in messages or []:
            media = media_in(item)
            if media is None:
                skipped += 1
                continue
            size = media_size(media)
            if size > MAX_BOT_DOWNLOAD:
                failed += 1
                continue
            try:
                source = await item.download()
                stored = storage.save_path(
                    message.from_user.id,
                    source,
                    name=media_name(media),
                    quota_bytes=allowance(message.from_user.id),
                )
            except Exception:  # noqa: BLE001 - one bad file must not stop the batch
                logger.warning("batch item save unconfirmed")
                failed += 1
                continue
            saved.append(stored)
            total += stored.size
        logger.info(
            "vault batch user=%s saved=%d skipped=%d failed=%d",
            message.from_user.id,
            len(saved),
            skipped,
            failed,
        )
        if not saved:
            await reply(
                message,
                panel(
                    "Nothing saved",
                    icon=ctx.theme.emoji("warn"),
                    subtitle=f"{count} message(s) read: {skipped} without a file, {failed} failed.",
                    note="Reply to the <b>first file</b> of the run, not to the command itself.",
                ),
            )
            return
        rows = [(stored.id, stored.name, human_bytes(stored.size)) for stored in saved[:10]]
        await reply(
            message,
            panel(
                "Batch saved",
                icon=ctx.theme.emoji("check"),
                subtitle=(
                    f"<b>{len(saved)}</b> file(s), {human_bytes(total)} total. "
                    f"{skipped} skipped, {failed} failed."
                ),
                table=Table(
                    headers=("Id", "Name", "Size"),
                    rows=tuple(rows),
                    aligns=("left", "left", "right"),
                ),
                lines=[f"Plus {len(saved) - len(rows)} more."] if len(saved) > len(rows) else [],
                note="Keep the IDs above. <code>/get &lt;id&gt;</code> sends back a file you own.",
            ),
        )

    def identified(handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, "Use your personal Telegram user identity for vault commands.")
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        **channel_commands,

        "get": get,
        "batch": batch,

    }
    # A specialized FileStore clone owns this command only when Linkshare is
    # absent. Never collide with /genlink in controller or combined suites.
    selected = tuple(getattr(ctx.settings, 'plugins', ()) or ())
    specialized = ((getattr(ctx.settings, 'db_scope', '') or '').startswith('clone:')
                   and 'filestore' in selected and 'linkshare' not in selected and '*' not in selected)
    conversation.direct_uploads = specialized
    manifest = MANIFEST
    if specialized:
        async def genlink(client, message):
            if len(_args(message)) != 1:
                await reply(message, 'Send /genlink without arguments, then send or forward one message to this bot. Use /batch for a range.')
                return
            await conversation.start(client, message, 'genlink')
            original = getattr(message, 'reply_to_message', None)
            if original is not None:
                await conversation.receive(client, original)
        async def selected_batch(client, message):
            if len(_args(message)) == 1 and not getattr(message, 'reply_to_message', None):
                await conversation.start(client, message, 'custom_selection')
                return
            await original_generate(client, message)
        handlers['custom_batch'] = selected_batch
        handlers.pop('get')
        handlers['genlink'] = genlink
        manifest = replace(MANIFEST, commands=tuple('genlink' if name == 'get' else name for name in MANIFEST.commands),
                           description='FileStore archive links: guided single-message and batch creation with private delivery.')
    return manifest, {name: identified(handler) for name, handler in handlers.items()}


def extra_handlers(ctx):
    from pyrogram import filters
    from pyrogram.handlers import MessageHandler
    conversation = ctx._filestore_conversation

    async def receive(client, message):
        # Direct files are a FileStore-only clone front door, not a controller
        # upload interceptor. Active batch conversations retain their semantics.
        if (getattr(conversation, 'direct_uploads', False)
                and conversation.state is None
                and getattr(getattr(message, 'from_user', None), 'id', None) == ctx.settings.owner_id
                and media_in(message) is not None):
            await conversation.start(client, message, 'genlink')
        await conversation.receive(client, message)

    return [MessageHandler(receive, filters.private)]
