"""Filestore — a per-member vault, from Meikoagent's ``file_store`` plugin.

The command names are Meikoagent's (``fsave``, ``get``, ``files``, ``del``,
``storestats``, ``storequota``); the storage is this repository's shared
:class:`~agent.platform.storage.Storage` instead of SQLAlchemy.

One hard limit is stated instead of hidden: **the Bot API will not let a bot
download a file larger than 20 MB.** A vault that silently refused big files
would look broken, so ``/fsave`` names the cap and the size it saw.

Scope is personal: every member's vault is keyed by their user id, and ``/get``
only releases files the caller owns. A file id from somebody else's vault is
answered with "not in your vault", never with the file.
"""

from __future__ import annotations

import logging
import time

from ..platform.manifest import PluginManifest
from ..ui.tables import Table, kv_table, panel
from ..ui.screens import format_uptime
from ..utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="filestore",
    name="Filestore",
    version="1.0.0",
    description="Per-member file vault: save, fetch, list and delete, with quotas.",
    commands=("fsave", "get", "files", "del", "storestats", "storequota"),
    permissions=("messages.read", "messages.send", "storage.read", "storage.write"),
    scope="all",
)

#: Telegram's Bot API download cap for bots, in bytes.
MAX_BOT_DOWNLOAD = 20 * 1024 * 1024
PAGE_SIZE = 10


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover - unreachable


def media_of(message):
    """The single media object a reply carries, if any."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    for attribute in ("document", "video", "audio", "voice", "animation", "photo"):
        media = getattr(replied, attribute, None)
        if media is not None:
            return replied, media
    return None


def media_size(media) -> int:
    size = getattr(media, "file_size", None)
    if size:
        return int(size)
    # Photos arrive as a list of sizes; the last one is the largest.
    if isinstance(media, list) and media:
        return int(getattr(media[-1], "file_size", 0) or 0)
    return 0


def media_name(media) -> str:
    name = getattr(media, "file_name", None)
    if name:
        return name
    if isinstance(media, list):
        return "photo.jpg"
    kind = getattr(media, "mime_type", None) or "file"
    return str(kind).replace("/", ".")


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def build(ctx):
    storage = ctx.storage

    def _quota_rows(owner_id: int) -> list[tuple[str, str]]:
        used = storage.usage(owner_id)
        quota = storage.quota_bytes
        return [
            ("Files", str(len(storage.list_owned(owner_id)))),
            ("Used", human_bytes(used)),
            ("Quota", human_bytes(quota)),
            ("Free", human_bytes(max(0, quota - used))),
        ]

    # -- /fsave ------------------------------------------------------------

    async def fsave(client, message):
        found = media_of(message)
        if found is None:
            await reply(message, 
                "Reply to a file with <code>/fsave</code> to keep it in your vault."
            )
            return
        replied, media = found
        size = media_size(media)
        if size > MAX_BOT_DOWNLOAD:
            await reply(message, 
                f"<b>Too large to save</b>\nFile: {human_bytes(size)}\n"
                f"Limit: {human_bytes(MAX_BOT_DOWNLOAD)} — that is the Bot API's "
                "download cap for bots, not a setting of mine."
            )
            return
        name = media_name(media)
        try:
            source = await replied.download()
            stored = storage.save_path(message.from_user.id, source, name=name)
        except Exception as exc:  # noqa: BLE001 - quota errors and IO reach the user
            logger.exception("fsave failed")
            await reply(message, f"Could not save that file: {type(exc).__name__}: {exc}")
            return
        rows = [
            ("Name", stored.name),
            ("Size", human_bytes(stored.size)),
            ("Id", stored.id),
        ] + _quota_rows(message.from_user.id)
        await reply(message, 
            panel(
                "Saved to your vault",
                icon=ctx.theme.emoji("check"),
                subtitle="Retrieve it any time with <code>/get &lt;id&gt;</code>.",
                table=kv_table(rows),
                footer="Files are private to you; nobody else can fetch them.",
            )
        )

    # -- /get --------------------------------------------------------------

    async def get(client, message):
        args = _args(message)
        if len(args) < 2:
            await reply(message, 
                "Usage: <code>/get &lt;id&gt;</code> — see <code>/files</code> for your ids."
            )
            return
        file_id = args[1].strip()
        stored = storage.get(file_id)
        if stored is None or stored.owner_id != message.from_user.id:
            await reply(message, "That id is not in your vault.")
            return
        path = storage.path_for(stored)
        if not path.exists():
            await reply(message, 
                "That entry is indexed but the file is gone from disk. "
                "Delete it with <code>/del</code> and save it again."
            )
            return
        try:
            await client.send_document(
                message.chat.id, str(path), file_name=stored.name
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("get failed")
            await reply(message, f"Could not send that file: {type(exc).__name__}")

    # -- /files ------------------------------------------------------------

    async def files(client, message):
        owned = storage.list_owned(message.from_user.id)
        if not owned:
            await reply(message, 
                panel(
                    "Your vault",
                    icon=ctx.theme.emoji("stats"),
                    lines=["Nothing stored yet."],
                    note="Reply to a file with <code>/fsave</code> to start.",
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
            for stored in owned[:PAGE_SIZE]
        )
        more = len(owned) - len(rows)
        await reply(message, 
            panel(
                "Your vault",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"<b>{len(owned)}</b> file(s), newest first.",
                table=Table(
                    headers=("Id", "Name", "Size", "Age"),
                    rows=rows,
                    aligns=("left", "left", "right", "right"),
                ),
                lines=[f"Plus {more} older file(s)."] if more > 0 else [],
                note="<code>/get &lt;id&gt;</code> re-sends one, <code>/del &lt;id&gt;</code> removes it.",
            )
        )

    # -- /del --------------------------------------------------------------

    async def delete(client, message):
        args = _args(message)
        if len(args) < 2:
            await reply(message, "Usage: <code>/del &lt;id&gt;</code>")
            return
        file_id = args[1].strip()
        stored = storage.get(file_id)
        if stored is None or stored.owner_id != message.from_user.id:
            await reply(message, "That id is not in your vault.")
            return
        storage.delete(file_id, owner_id=message.from_user.id)
        await reply(message, 
            f"Deleted <code>{stored.id}</code> ({stored.name}, {human_bytes(stored.size)})."
        )

    # -- /storestats and /storequota ---------------------------------------

    async def storestats(client, message):
        owner_id = message.from_user.id
        owned = storage.list_owned(owner_id)
        newest = owned[0] if owned else None
        lines = []
        if newest is not None:
            lines.append(
                f"Newest: <code>{newest.id}</code> — {newest.name} "
                f"({human_bytes(newest.size)})"
            )
        await reply(message, 
            panel(
                "Vault statistics",
                icon=ctx.theme.emoji("stats"),
                subtitle="Measured from the store on disk, not counted separately.",
                table=kv_table(_quota_rows(owner_id)),
                lines=lines,
                footer="One vault per user id.",
            )
        )

    async def storequota(client, message):
        owner_id = message.from_user.id
        used = storage.usage(owner_id)
        quota = storage.quota_bytes
        percent = (used / quota * 100) if quota else 0
        await reply(message, 
            panel(
                "Vault quota",
                icon=ctx.theme.emoji("shield"),
                table=kv_table(
                    [
                        ("Used", human_bytes(used)),
                        ("Quota", human_bytes(quota)),
                        ("Used %", f"{percent:.0f}%"),
                    ]
                ),
                note=(
                    "A save that would cross the quota is refused before anything is "
                    "written. Raising it is a deploy setting, not a command."
                ),
                footer="Shared with <code>/genlink</code>; one store, not two.",
            )
        )

    return MANIFEST, {
        "fsave": fsave,
        "get": get,
        "files": files,
        "del": delete,
        "storestats": storestats,
        "storequota": storequota,
    }
