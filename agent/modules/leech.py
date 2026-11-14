"""Leech — HTTP(S) downloads that actually land, from Meikoagent's ``leech``.

Meikoagent ships a transfer engine with pluggable backends (local, aria2,
qBittorrent, rclone). Only the *local* backend can be honest here: aria2, rclone
and qBittorrent are external daemons that this image does not run, so
``/taskbackend`` reports which of them exist on the host instead of pretending
to use them.

What is real without any of them:

* ``/leech <url>`` streams an ``http(s)`` file to disk with progress, then sends
  it to the chat as a document;
* ``/mirror <url>`` does the same and also keeps it in the filestore;
* ``/tasklist`` ``/taskstatus`` ``/leechstats`` read the shared job queue, so
  ``/cancel`` (from the core module) stops these transfers like any other job.

Safety worth stating: URLs are checked before a request is made. Only
``http``/``https``, no embedded credentials, and no host that resolves to a
loopback, private, link-local or reserved address — a bot that will fetch
``http://127.0.0.1:8080`` on command is a server-side request forgery gadget.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from ..platform.manifest import PluginManifest
from ..platform.net import LinkError, check_target, human_bytes, parse_url
from ..ui.tables import Table, kv_table, panel
from ..utils.rich import reply

logger = logging.getLogger(__name__)

#: The module's own name for the shared error type.
LeechError = LinkError

MANIFEST = PluginManifest(
    slug="leech",
    name="Leech",
    version="1.0.0",
    description="Download an http(s) file with progress and deliver it to the chat.",
    commands=("leech", "mirror", "tasklist", "taskstatus", "leechstats", "taskbackend"),
    permissions=("messages.read", "messages.send", "storage.write", "http.outbound"),
    scope="all",
)

#: Refuse anything bigger than this before writing a byte to disk.
MAX_BYTES = 2 * 1024 * 1024 * 1024
CHUNK = 1024 * 256
PROGRESS_INTERVAL = 2.0
def _destination(url: str) -> Path:
    name = Path(urlsplit(url).path).name or "download.bin"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:80]
    return Path(tempfile.mkdtemp(prefix="leech-")) / (safe or "download.bin")


async def download(url: str, destination: Path, on_progress=None) -> int:
    """Stream *url* to *destination*; returns the byte count."""
    written = 0
    started = time.monotonic()
    last_report = 0.0
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status >= 400:
                raise LeechError(f"the server answered HTTP {response.status}")
            total = int(response.headers.get("Content-Length") or 0)
            if total and total > MAX_BYTES:
                raise LeechError(
                    f"that file is {human_bytes(total)}; the limit is {human_bytes(MAX_BYTES)}"
                )
            with destination.open("wb") as handle:
                async for chunk in response.content.iter_chunked(CHUNK):
                    handle.write(chunk)
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise LeechError("the download passed the size limit")
                    now = time.monotonic()
                    if on_progress is not None and now - last_report >= PROGRESS_INTERVAL:
                        last_report = now
                        await on_progress(written, total, now - started)
    return written


def backends() -> list[tuple[str, str, str]]:
    """(backend, available, note) for every backend Meikoagent can drive."""
    rows = [("local", "yes", "built in — streams with aiohttp")]
    for binary, label in (
        ("aria2c", "aria2"),
        ("rclone", "rclone"),
        ("qbittorrent-nox", "qBittorrent"),
        ("yt-dlp", "yt-dlp"),
    ):
        path = shutil.which(binary)
        rows.append(
            (label, "yes" if path else "no", path or "not installed — not offered")
        )
    return rows


def build(ctx):
    async def _progress_message(client, message, label: str):
        """Return an edit target plus a throttled callback."""
        try:
            sent = await reply(message, f"<b>{label}</b>\nStarting…")
        except Exception:  # noqa: BLE001 - progress is a nicety
            return None, None
        chat_id = message.chat.id
        message_id = getattr(sent, "id", None)

        async def report(done: int, total: int, elapsed: float) -> None:
            if message_id is None:
                return
            speed = done / elapsed if elapsed > 0 else 0
            share = f"{done * 100 // total}%" if total else human_bytes(done)
            text = (
                f"<b>{label}</b>\n"
                f"Downloaded: {human_bytes(done)}"
                + (f" of {human_bytes(total)} ({share})" if total else f" ({share})")
                + f"\nSpeed: {human_bytes(speed)}/s"
            )
            try:
                await client.edit_message_text(chat_id, message_id, text)
            except Exception:  # noqa: BLE001 - edits are best effort
                logger.debug("progress edit failed", exc_info=True)

        return message_id, report

    def _job_body(url: str, *, keep: bool):
        async def runner(job):
            destination = _destination(url)
            job.detail = "downloading"
            written = await download(url, destination, on_progress=job.progress_hook)
            job.progress = 1.0
            job.detail = f"downloaded {human_bytes(written)}"
            if keep:
                stored = ctx.storage.save_path(
                    job.owner_id, destination, name=destination.name
                )
                job.detail = f"stored as {stored.id}"
            return destination

        return runner

    # -- /leech and /mirror ------------------------------------------------

    async def _submit(client, message, *, keep: bool) -> None:
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        raw = parts[1].strip() if len(parts) > 1 else ""
        try:
            url = parse_url(raw)
            await check_target(url)
        except LeechError as exc:
            await reply(message, f"<b>Not fetching that</b>\n{exc}.")
            return
        label = f"{'Mirror' if keep else 'Leech'}: <code>{Path(urlsplit(url).path).name or url}</code>"
        _message_id, report = await _progress_message(client, message, label)

        async def runner(job):
            destination = _destination(url)
            job.detail = "downloading"
            written = await download(url, destination, on_progress=report)
            job.progress = 1.0
            job.detail = f"downloaded {human_bytes(written)}"
            if keep:
                stored = ctx.storage.save_path(
                    job.owner_id, destination, name=destination.name
                )
                job.detail = f"stored as {stored.id} ({human_bytes(stored.size)})"
                await reply(message, 
                    panel(
                        "Mirrored",
                        icon=ctx.theme.emoji("check"),
                        table=kv_table(
                            [
                                ("File", stored.name),
                                ("Size", human_bytes(stored.size)),
                                ("Id", stored.id),
                            ]
                        ),
                        note="Fetch it later with <code>/get &lt;id&gt;</code>.",
                    )
                )
                return
            await client.send_document(
                message.chat.id, str(destination), file_name=destination.name
            )

        job = ctx.jobs.submit("leech", message.from_user.id, runner, label=label[:60])
        await reply(message, 
            f"Job <code>{job.id}</code> started. <code>/taskstatus {job.id}</code> "
            "to watch it, <code>/cancel</code> to stop it."
        )

    async def leech(client, message):
        await _submit(client, message, keep=False)

    async def mirror(client, message):
        await _submit(client, message, keep=True)

    # -- queue reporting ---------------------------------------------------

    async def tasklist(client, message):
        jobs = ctx.jobs.for_owner(message.from_user.id)
        if not jobs:
            await reply(message, 
                panel(
                    "Your tasks",
                    icon=ctx.theme.emoji("stats"),
                    lines=["Nothing queued."],
                    note="Start one with <code>/leech &lt;url&gt;</code>.",
                )
            )
            return
        rows = tuple(
            (
                job.id,
                job.state.value,
                f"{int(job.progress * 100)}%",
                (job.label or job.detail or "—")[:40],
            )
            for job in jobs[-10:]
        )
        await reply(message, 
            panel(
                "Your tasks",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"<b>{len(jobs)}</b> task(s) this run.",
                table=Table(
                    headers=("Id", "State", "Done", "What"),
                    rows=rows,
                    aligns=("left", "left", "right", "left"),
                    total_width=56,
                ),
                note="<code>/taskstatus &lt;id&gt;</code> for the detail of one.",
                footer="Jobs live in this process; a restart clears them.",
            )
        )

    async def taskstatus(client, message):
        parts = (getattr(message, "text", "") or "").split()
        if len(parts) < 2:
            await reply(message, "Usage: <code>/taskstatus &lt;id&gt;</code>")
            return
        job = ctx.jobs.get(parts[1])
        if job is None or job.owner_id != message.from_user.id:
            await reply(message, "No task of yours has that id.")
            return
        rows = [
            ("Id", job.id),
            ("Module", job.module),
            ("State", job.state.value),
            ("Progress", f"{int(job.progress * 100)}%"),
            ("Detail", job.detail or job.label or "—"),
        ]
        if job.error:
            rows.append(("Error", job.error[:200]))
        await reply(message, 
            panel(
                "Task",
                icon=ctx.theme.emoji("bolt"),
                table=kv_table(rows),
                footer="<code>/cancel</code> stops everything you have running.",
            )
        )

    async def leechstats(client, message):
        jobs = ctx.jobs.for_owner(message.from_user.id)
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.state.value] = counts.get(job.state.value, 0) + 1
        rows = [(state, str(count)) for state, count in sorted(counts.items())]
        await reply(message, 
            panel(
                "Leech statistics",
                icon=ctx.theme.emoji("stats"),
                table=kv_table(rows) if rows else None,
                lines=[] if rows else ["Nothing has been queued by you this run."],
                footer=f"{len(ctx.jobs.active())} task(s) active across the bot.",
            )
        )

    async def taskbackend(client, message):
        rows = tuple(backends())
        await reply(message, 
            panel(
                "Transfer backends",
                icon=ctx.theme.emoji("gear"),
                subtitle="Determined with <code>shutil.which</code>, not from config.",
                table=Table(
                    headers=("Backend", "Ready", "Note"),
                    rows=rows,
                    total_width=56,
                ),
                note=(
                    "Only <code>local</code> is used. An absent daemon is listed as "
                    "absent rather than enabled."
                ),
                footer="aria2/rclone/qBittorrent would need a service this image does not run.",
            )
        )

    return MANIFEST, {
        "leech": leech,
        "mirror": mirror,
        "tasklist": tasklist,
        "taskstatus": taskstatus,
        "leechstats": leechstats,
        "taskbackend": taskbackend,
    }
