"""Leech — HTTP(S) downloads that land on disk and come back as a file.

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

from ...platform.attachments import attachment_kwargs
from ...platform.manifest import PluginManifest
from ...platform.net import LinkError, check_target, human_bytes, parse_url
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply
from .transfer import _destination, download

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


def backends() -> list[tuple[str, str, str]]:
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
                book = getattr(ctx, "premium", None)
                allowance = (
                    book.tier(job.owner_id).quota_bytes if book is not None else None
                )
                stored = ctx.storage.save_path(
                    job.owner_id,
                    destination,
                    name=destination.name,
                    quota_bytes=allowance,
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
        except LeechError:
            logger.info("leech URL refused user=%s", message.from_user.id)
            await reply(message, "<b>Not fetching that</b>\nUse one public HTTP(S) URL without embedded credentials; the address could not be validated.")
            return

        book = getattr(ctx, "premium", None)
        user_id = message.from_user.id
        if book is not None and not book.take(user_id, "leech"):
            tier = book.tier(user_id)
            logger.info("leech refused: daily allowance spent user=%s tier=%s", user_id, tier.slug)
            await reply(
                message,
                panel(
                    "Daily allowance spent",
                    icon=ctx.theme.emoji("shield"),
                    table=kv_table(
                        [
                            ("Tier", tier.label),
                            ("Transfers/day", str(tier.transfers_per_day)),
                        ]
                    ),
                    note=(
                        "The counter resets at midnight UTC. "
                        "<code>/premium</code> shows the tier that raises it."
                    ),
                    footer="Refused before any download started, so nothing was written.",
                ),
            )
            return
        # Avoid persisting source URLs/query tokens in task labels or logs.
        label = 'Mirror transfer' if keep else 'Leech transfer'
        logger.info('transfer queued user=%s kind=%s', user_id, 'mirror' if keep else 'leech')
        _message_id, report = await _progress_message(client, message, label)

        async def runner(job):
            destination = _destination(url)
            job.detail = "downloading"
            written = await download(url, destination, on_progress=report)
            job.progress = 1.0
            job.detail = f"downloaded {human_bytes(written)}"
            if keep:
                book = getattr(ctx, "premium", None)
                allowance = (
                    book.tier(job.owner_id).quota_bytes if book is not None else None
                )
                stored = ctx.storage.save_path(
                    job.owner_id,
                    destination,
                    name=destination.name,
                    quota_bytes=allowance,
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
                message.chat.id,
                str(destination),
                file_name=destination.name,
                **attachment_kwargs(
                    ctx.chats,
                    message.chat.id,
                    name=destination.name,
                    size=human_bytes(destination.stat().st_size),
                ),
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
        args = (getattr(message, 'text', '') or '').split()[1:]
        if len(args) > 1 or (args and (not args[0].isascii() or not args[0].isdecimal() or len(args[0]) > 8 or int(args[0]) < 1)):
            await reply(message, 'Usage: <code>/tasklist [page]</code>, starting at page 1.')
            return
        page = int(args[0]) if args else 1
        jobs = list(reversed(ctx.jobs.for_owner(message.from_user.id)))
        pages = max(1, (len(jobs) + 9) // 10)
        if page > pages:
            await reply(message, f'Choose a task page from 1 to {pages}.')
            return
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
                job.module,
            )
            for job in jobs[(page - 1) * 10:page * 10]
        )
        await reply(message, 
            panel(
                "Your tasks",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"{ctx.theme.emoji('diamond')} Page <b>{page}/{pages}</b> · {len(jobs)} retained task(s), newest first.",
                table=Table(
                    headers=("Id", "State", "Done", "Module"),
                    rows=rows,
                    aligns=("left", "left", "right", "left"),
                    total_width=56,
                ),
                lines=([f"<code>/tasklist {page - 1}</code> previous"] if page > 1 else []) +
                      ([f"<code>/tasklist {page + 1}</code> next"] if page < pages else []),
                note="<code>/taskstatus &lt;id&gt;</code> for one. Labels are omitted to avoid exposing source URLs from older jobs.",
                footer="Jobs live in this process; a restart clears them.",
            )
        )

    async def taskstatus(client, message):
        parts = (getattr(message, "text", "") or "").split()
        if len(parts) != 2:
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
            ("Detail", "withheld: task details may contain private paths or URLs"),
        ]
        if job.error:
            rows.append(("Error", "Task failed; raw provider/tool errors are withheld."))
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
        book = getattr(ctx, "premium", None)
        if book is not None:
            tier = book.tier(message.from_user.id)
            rows.append(("Tier", tier.label))
            rows.append(
                (
                    "Left today",
                    f"{book.remaining(message.from_user.id, 'leech')} / {tier.transfers_per_day}",
                )
            )
        await reply(message, 
            panel(
                "Leech statistics",
                icon=ctx.theme.emoji("stats"),
                table=kv_table(rows) if rows else None,
                lines=[] if rows else ["Nothing has been queued by you this run."],
                footer=f"{sum(not job.finished for job in jobs)} of your tasks active. Counts cover retained shared jobs, not only transfers.",
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

    def validated(name, handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, 'from_user', None), 'id', None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, 'Use your personal Telegram user identity for transfer commands.')
                return
            args = (getattr(message, 'text', '') or '').split()[1:]
            if name in ('leechstats', 'taskbackend') and args:
                await reply(message, f'Usage: <code>/{name}</code> without arguments.')
                return
            if name in ('leech', 'mirror') and len(args) != 1:
                await reply(message, panel('Transfer options', icon=ctx.theme.emoji('info'),
                    lines=[f'Usage: <code>/{name} &lt;public_http_url&gt;</code>. Supply exactly one URL.'],
                    note='Transfers and task responses are visible in the current chat. Do not submit secret links.'))
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        "leech": leech,
        "mirror": mirror,
        "tasklist": tasklist,
        "taskstatus": taskstatus,
        "leechstats": leechstats,
        "taskbackend": taskbackend,
    }
    return MANIFEST, {name: validated(name, handler) for name, handler in handlers.items()}
