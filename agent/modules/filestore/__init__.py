"""Filestore — a per-member vault on the shared storage layer.

One hard limit is stated instead of hidden: **the Bot API will not let a bot
download a file larger than 20 MB.** A vault that silently refused big files
would look broken, so batch saves enforce the size cap.

Scope is personal: every member's vault is keyed by their user id, and ``/get``
only releases files the caller owns. A file id from somebody else's vault is
answered with "not in your vault", never with the file.
"""

from __future__ import annotations

import logging
import time

from ...platform.attachments import attachment_kwargs
from ...platform.manifest import PluginManifest
from ...ui.tables import Table, kv_table, panel
from ...ui.screens import format_uptime
from ...utils.delivery import send_stored
from ...utils.rich import reply
from .vault import (
    MAX_BATCH,
    MAX_BOT_DOWNLOAD,
    PAGE_SIZE,
    _args,
    human_bytes,
    media_in,
    media_name,
    media_size,
)

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="filestore",
    name="Filestore",
    version="1.0.0",
    description="Per-member file vault: save, fetch, list and delete, with quotas.",
    commands=("get", "files", "batch", "check", "del"),
    permissions=("messages.read", "messages.send", "storage.read", "storage.write"),
    scope="all",
)

#: Telegram's Bot API download cap for bots, in bytes.


def build(ctx):
    storage = ctx.storage

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

    # -- /fsave ------------------------------------------------------------


    # -- /get --------------------------------------------------------------

    async def get(client, message):
        args = _args(message)
        if len(args) != 2:
            await reply(message, 
                "Usage: <code>/get &lt;id&gt;</code> — see <code>/files</code> for your ids."
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
                note="<code>/files</code> lists everything, <code>/get &lt;id&gt;</code> sends one back.",
            ),
        )

    # -- /check ------------------------------------------------------------

    async def check(_client, message):
        """Everything this vault knows about one id."""
        parts = _args(message)
        if len(parts) != 2:
            await reply(message, "Usage: <code>/check &lt;id&gt;</code>")
            return
        stored = storage.get(parts[1].strip())
        if stored is None or stored.owner_id != message.from_user.id:
            await reply(message, "That id is not in your vault.")
            return
        path = storage.path_for(stored)
        links = [
            record
            for record in ctx.links.owned(message.from_user.id)
            if record.file_id == stored.id and not record.revoked
        ]
        await reply(
            message,
            panel(
                "Vault entry",
                icon=ctx.theme.emoji("info"),
                table=kv_table(
                    [
                        ("Id", stored.id),
                        ("Name", stored.name),
                        ("Size", human_bytes(stored.size)),
                        ("On disk", "yes" if path.exists() else "missing"),
                        ("Links", str(len(links))),
                        ("Telegram reference", "recorded" if stored.telegram_file_id else "not recorded"),
                    ]
                ),
                note="A recorded Telegram reference may allow retrieval after local bytes disappear; it is not a live availability check.",
                footer="/get id · /del id · deleting metadata does not erase delivered copies.",
            ),
        )

    # -- /files ------------------------------------------------------------

    async def files(client, message):
        parts = _args(message)
        if len(parts) > 2 or (len(parts) == 2 and (not parts[1].isascii() or not parts[1].isdecimal()
                or len(parts[1]) > 8 or int(parts[1]) < 1)):
            await reply(message, "Usage: <code>/files [page]</code>, starting at page 1.")
            return
        page = int(parts[1]) if len(parts) == 2 else 1
        owned = storage.list_owned(message.from_user.id)
        pages = max(1, (len(owned) + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > pages:
            await reply(message, f"Choose a vault page from 1 to {pages}.")
            return
        if not owned:
            await reply(message, 
                panel(
                    "Your vault",
                    icon=ctx.theme.emoji("stats"),
                    lines=["Nothing stored yet."],
                    note="Reply to a file with <code>/batch 1</code> to start.",
                )
            )
            return
        now = time.time()
        rows = tuple(
            (
                stored.id,
                stored.name,
                human_bytes(stored.size),
                format_uptime(now - stored.created_at),
            )
            for stored in owned[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        )
        navigation = []
        if page > 1:
            navigation.append(f"<code>/files {page - 1}</code> previous")
        if page < pages:
            navigation.append(f"<code>/files {page + 1}</code> next")
        await reply(message, 
            panel(
                "Your vault",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"{ctx.theme.emoji('diamond')} Page <b>{page}/{pages}</b> · <b>{len(owned)}</b> file(s), newest first.",
                table=Table(
                    headers=("Id", "Name", "Size", "Age"),
                    rows=rows,
                    aligns=("left", "left", "right", "right"),
                ),
                lines=[" · ".join(navigation)] if navigation else [],
                note="<code>/get &lt;id&gt;</code> re-sends one, <code>/del &lt;id&gt;</code> removes it.",
            )
        )

    # -- /del --------------------------------------------------------------

    async def delete(client, message):
        args = _args(message)
        if len(args) != 2:
            await reply(message, "Usage: <code>/del &lt;id&gt;</code>")
            return
        file_id = args[1].strip()
        stored = storage.get(file_id)
        if stored is None or stored.owner_id != message.from_user.id:
            await reply(message, "That id is not in your vault.")
            return
        storage.delete(file_id, owner_id=message.from_user.id)
        logger.info("vault delete user=%s id=%s", message.from_user.id, file_id)
        await reply(message, 
            panel("Vault entry deleted", icon=ctx.theme.emoji("check"),
                table=kv_table([("Id", stored.id), ("Name", stored.name), ("Size", human_bytes(stored.size))]),
                note="Removed from your vault. Previously delivered or archived copies are not remotely erased.", footer="/files")
        )

    # -- /storestats and /storequota ---------------------------------------


    def identified(handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, "Use your personal Telegram user identity for vault commands.")
                return
            return await handler(client, message)
        return wrapped

    handlers = {

        "get": get,
        "files": files,
        "batch": batch,
        "check": check,
        "del": delete,

    }
    return MANIFEST, {name: identified(handler) for name, handler in handlers.items()}
