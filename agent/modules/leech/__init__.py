"""Leech — HTTP(S) downloads that land on disk and come back as a file.

* ``/leech <url>`` streams an ``http(s)`` file to disk with progress, then sends
  it to the chat as a document;
* ``/mirror <url>`` does the same and also keeps it in the filestore;
* ``/cancel`` (from the core module) stops owned transfers like other jobs.

Safety worth stating: URLs are checked before a request is made. Only
``http``/``https``, no embedded credentials, and no host that resolves to a
loopback, private, link-local or reserved address — a bot that will fetch
``http://127.0.0.1:8080`` on command is a server-side request forgery gadget.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from ...platform.attachments import attachment_kwargs
from ...platform.manifest import PluginManifest
from ...platform.net import LinkError, check_target, human_bytes, parse_url
from ...ui.tables import kv_table, panel
from ...utils.rich import reply
from .transfer import _destination, download
from urllib.parse import urlsplit
from pathlib import Path
from .options import parse_message
from .typetube import youtube_url, resolve_audio, available as typetube_available
from ...platform.media_rules import transform

logger = logging.getLogger(__name__)

#: The module's own name for the shared error type.
LeechError = LinkError

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=True,
    slug="leech",
    name="Leech",
    version="1.0.0",
    description="Download an http(s) file with progress and deliver it to the chat.",
    commands=("leech", "mirror", "set_caption", "see_caption", "del_caption", "set_thumb", "view_thumb", "see_thumb", "del_thumb", "delete_thumb"),
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
    rows.append(("TypeTube", "yes" if typetube_available() else "no", "YouTube audio via public cluster"))
    return rows


def _destination_name(url):
    return Path(urlsplit(url).path).name or "download.bin"


def build(ctx):
    from .home import build as build_panel
    show_home = build_panel(ctx)

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
            except Exception as error:  # noqa: BLE001 - edits are best effort
                logger.debug("#Errors Transfer progress edit unconfirmed (%s)", type(error).__name__)

        return message_id, report

    # -- /leech and /mirror ------------------------------------------------

    async def _submit(client, message, *, keep: bool) -> None:
        raw, output_name = parse_message(message)
        try:
            url = parse_url(raw)
            await check_target(url)
            youtube = youtube_url(url)
        except (LeechError, ValueError):
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
            destination = None
            try:
                source, suggested = url, _destination_name(url)
                if youtube:
                    job.detail = "resolving YouTube audio with TypeTube"
                    source, suggested = await resolve_audio(youtube)
                name = transform(ctx.chats, message.chat.id, output_name or suggested)
                destination = _destination(source, name)
                job.detail = "downloading"
                written = await download(source, destination, on_progress=report)
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
                job.detail = "Downloaded; Telegram delivery unconfirmed"
                sent = await client.send_document(
                    message.chat.id,
                    str(destination),
                    file_name=destination.name,
                    **attachment_kwargs(
                        ctx.chats,
                        message.chat.id,
                        name=destination.name,
                        size=human_bytes(destination.stat().st_size),
                        apply_rules=False,
                    ),
                )
                if type(getattr(sent, 'id', None)) is not int or sent.id <= 0:
                    raise RuntimeError("Delivery acknowledgement unavailable")
                job.detail = "Telegram delivery acknowledged"

            except asyncio.CancelledError:
                try:
                    text = "Transfer cancelled. Temporary files are being removed."
                    if 'delivery unconfirmed' in job.detail.lower():
                        text += " Delivery may already have happened. Check this chat before retrying; no automatic resend was attempted."
                    await reply(message, text)
                except Exception:
                    logger.warning("Transfer cancellation notice could not be delivered")
                raise
            except Exception:
                try:
                    if 'delivery unconfirmed' in job.detail.lower():
                        await reply(message, "Telegram delivery was not confirmed. Check this chat before retrying; no automatic resend was attempted. Temporary files are being removed. Check /jobs.")
                    else:
                        await reply(message, "Transfer failed. The download, storage or Telegram delivery could not be confirmed. Temporary files are being removed. Check /jobs before retrying.")
                except Exception:
                    logger.warning("Transfer failure notice could not be delivered")
                raise
            finally:
                if destination is not None:
                    cleanup_failed = False
                    # Cleanup is secondary to delivery/failure/cancellation. Only
                    # touch this transfer's file and newly owned directory; never
                    # recurse or let a filesystem error replace the runner outcome.
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError as error:
                        cleanup_failed = True
                        logger.warning("#Errors Transfer file cleanup unconfirmed (%s)", type(error).__name__)
                    try:
                        destination.parent.rmdir()
                    except FileNotFoundError:
                        pass  # already absent is a confirmed clean directory
                    except OSError as error:
                        cleanup_failed = True
                        logger.warning("#Errors Transfer directory cleanup unconfirmed (%s)", type(error).__name__)
                    if cleanup_failed:
                        job.detail = (job.detail + "; " if job.detail else "") + "Temporary cleanup unconfirmed"
                        try:
                            await asyncio.wait_for(reply(message,
                                "Temporary cleanup is unconfirmed; a local temporary file or directory may remain. "
                                "This does not change the transfer outcome. Check /jobs; do not resend just to clean up."), timeout=5)
                        except Exception as error:
                            logger.warning("#Errors Transfer cleanup notice unconfirmed (%s)", type(error).__name__)

        job = ctx.jobs.submit("leech", message.from_user.id, runner, label=label[:60])
        await reply(message,
            f"Job <code>{job.id}</code> started. "
            "Use <code>/cancel</code> to stop it."
        )

    async def leech(client, message):
        await _submit(client, message, keep=False)

    async def mirror(client, message):
        await _submit(client, message, keep=True)

    # -- queue reporting ---------------------------------------------------


    def validated(name, handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, 'from_user', None), 'id', None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, 'Use your personal Telegram user identity for transfer commands.')
                return
            text = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''
            if len(text.split()) == 1 and not getattr(message, 'reply_to_message', None):
                await show_home(message)
                return
            try:
                parse_message(message)
            except ValueError:
                await reply(message, panel('Transfer options', icon=ctx.theme.emoji('info'),
                    lines=[f'Usage: <code>/{name} &lt;public_http_url&gt; [-n "output name.ext"]</code>.'],
                    note='You can also reply to one public URL. Choose a filename without paths or control characters. Requests are visible in this chat; do not submit secret links.'))
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        "leech": leech,
        "mirror": mirror,

    }
    from .thumbnails import build as build_thumbnails
    from .captions import build as build_captions
    return MANIFEST, {**{name: validated(name, handler) for name, handler in handlers.items()},
                      **build_captions(ctx), **build_thumbnails(ctx)}
