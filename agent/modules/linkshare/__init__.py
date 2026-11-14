"""Linkshare module — share links that actually hand over a file.

A link has three parts and one job:

* **creation** — ``/genlink [hours] [uses]`` stores the replied file in the
  sender's vault and answers with a ``t.me/<bot>?start=link_<token>`` deep link,
  a copy button and a revoke button; ``/share <id> [hours] [uses]`` does the
  same for a file that is *already* in the vault, so sharing never copies it
  twice;
* **redemption** — opening that link lands on ``/start link_<token>``; the
  ``link`` prefix of the deep-link router resolves the token, checks it is not
  revoked, expired or used up, marks the use and sends the file;
* **control** — ``/links`` lists what is still alive with its remaining uses,
  ``/revoke`` kills one, and the panel's own button does the same without typing
  the token.

The module reuses the platform's storage and signer rather than keeping a private
store, and it never shows a storage identifier: the token is the handle.
"""

from __future__ import annotations

import html
import logging
import time

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.links import LinkError
from ...platform.manifest import PluginManifest
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils import rich as rich_ui
from ...utils.delivery import send_stored
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="linkshare",
    name="Linkshare",
    version="1.1.0",
    description="Share a stored file as a link that delivers it, with a use cap.",
    commands=("genlink", "share", "links", "revoke"),
    permissions=("messages.read", "storage.read", "storage.write"),
)

#: Callback prefix for the share panel's buttons.
PREFIX = "link"

#: Deep-link prefix this module owns: ``/start link_<token>``.
DEEP_PREFIX = "link"

#: Extensions Telegram should show as a playable video rather than a document.
VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

#: Explicit bounds; invalid values are rejected before any creation or download.
MAX_TTL_HOURS = 24 * 30
MAX_USES = 1000


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def _hours_left(record) -> float:
    return max(0.0, (record.expires_at - time.time()) / 3600)


def _uses_text(record) -> str:
    """What is left of the use cap, in words rather than a bare number."""
    if not record.max_uses:
        return "unlimited"
    left = record.remaining or 0
    return "used up" if left <= 0 else f"{left} of {record.max_uses} left"


async def _username(client) -> str:
    """This bot's @username, for a ``t.me`` link; ``""`` when Telegram hides it."""
    me = getattr(client, "me", None)
    if me is None:
        try:
            me = await client.get_me()
        except Exception:  # noqa: BLE001 - a missing username is cosmetic
            logger.debug("could not read the bot's own username", exc_info=True)
            return ""
    return getattr(me, "username", "") or ""


def _link_url(username: str, token: str) -> str:
    return f"https://t.me/{username}?start={DEEP_PREFIX}_{token}" if username else ""


def build(ctx):
    """Wire commands, the share panel and the redeem deep link."""

    def _panel(record, stored, username: str):
        """The share card: what it is, how long it lives, and how to send it."""
        url = _link_url(username, record.token)
        rows = [
            ("File", stored.name if stored else "file unavailable"),
            ("Size", f"{stored.size:,} bytes" if stored else "unknown"),
            ("Expires", f"in {_hours_left(record):.0f}h"),
            ("Uses", _uses_text(record)),
        ]
        # Always show a usable token, not just a link: a deployment whose bot
        # has no username (or a chat where the card is copied by hand) still
        # needs the thing /start takes.
        lines = [
            f"<code>{html.escape(url or f'link_{record.token}')}</code>"
        ]
        buttons = []
        if url:
            buttons.append(
                [Button("\U0001f4cb Copy link", copy_text=url, style=ButtonStyle.SUCCESS)]
            )
        buttons.append(
            [
                Button(
                    "\U0001f6ab Revoke",
                    callback_data=f"{PREFIX}:revoke:{record.token}",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
        buttons.append(
            [Button("\u21a9\ufe0f Menu", callback_data="menu:home", style=ButtonStyle.PRIMARY)]
        )
        body = panel(
            "Share link",
            icon=ctx.theme.emoji("link"),
            subtitle=(
                "Anyone with this link can fetch the file until it expires"
                + (" or runs out of uses." if record.max_uses else ".")
            ),
            table=kv_table(rows),
            lines=lines,
            note=(
                "Opening the link sends the file straight to that chat — no "
                "command to type."
                if url
                else "Telegram did not report this bot's username, so only the token "
                "is shown: send it as <code>/start link_&lt;token&gt;</code>."
            ),
            footer="/links lists your records. Revocation does not erase delivered copies; never share sensitive bearer links publicly.",
        )
        return body, Keyboard(buttons)

    def _limits(parts, command: str) -> tuple[int | None, int, str]:
        """``(ttl_hours, max_uses, problem)`` from the numbers after a command."""
        if len(parts) > 2 or any(not part.isascii() or not part.isdecimal() or len(part) > 4 for part in parts):
            return None, 0, f"Use <code>/{command}</code> with at most two whole numbers: hours (1–{MAX_TTL_HOURS}), then uses (0–{MAX_USES}; 0 means unlimited)."
        ttl = int(parts[0]) if parts else None
        uses = int(parts[1]) if len(parts) > 1 else 0
        if (ttl is not None and not 1 <= ttl <= MAX_TTL_HOURS) or not 0 <= uses <= MAX_USES:
            return None, 0, f"Choose hours from 1 to {MAX_TTL_HOURS} and uses from 0 to {MAX_USES}; 0 uses means unlimited. No link was created."
        return ttl, uses, ""

    async def _grant(client, message, stored, ttl, uses, *, source: str) -> None:
        """Create the link for *stored* and answer with the share card."""
        owner = message.from_user.id
        record = ctx.links.create(stored.id, owner, ttl_hours=ttl, max_uses=uses)
        if getattr(ctx, "events", None) is not None:
            ctx.events.emit("link", owner=owner, uses=uses)
        logger.info(
            "share link created by %s for %s from %s (ttl=%sh, uses=%s)",
            owner, stored.name, source, f"{_hours_left(record):.0f}",
            uses or "unlimited",
        )
        username = await _username(client)
        text, keyboard = _panel(record, stored, username)
        await reply(message, text, reply_markup=keyboard)

    async def share(client, message):
        """``/share <vault id> [hours] [uses]`` — link a file already stored."""
        parts = _args(message)[1:]
        if not parts:
            owned = ctx.storage.list_owned(message.from_user.id)
            await reply(
                message,
                panel(
                    "Share a stored file",
                    icon=ctx.theme.emoji("link"),
                    subtitle=(
                        f"Send <code>/share &lt;id&gt;</code> — you have "
                        f"<b>{len(owned)}</b> file(s) in the vault."
                        if owned
                        else "Your vault is empty: use <code>/batch</code> on replied files to save them."
                    ),
                    table=Table(
                        headers=("Id", "Name", "Size"),
                        rows=tuple(
                            (item.id, item.name, f"{item.size:,}")
                            for item in owned[:8]
                        ),
                        aligns=("left", "left", "right"),
                        max_column=26,
                        total_width=48,
                    )
                    if owned
                    else None,
                    note="Optional numbers after the id: hours, then uses.",
                    footer="<code>/files</code> lists the rest of the vault.",
                ),
                reply_markup=nav_keyboard(),
            )
            return
        stored = ctx.storage.get(parts[0])
        if stored is None or ctx.storage.owner_of(parts[0]) != message.from_user.id:
            await reply(
                message,
                "No file with that id in your vault. <code>/files</code> lists them.",
            )
            return
        ttl, uses, problem = _limits(parts[1:], "share")
        if problem:
            await reply(message, problem)
            return
        await _grant(client, message, stored, ttl, uses, source=f"/share {parts[0]}")

    async def genlink(client, message):
        replied = getattr(message, "reply_to_message", None)
        media = replied and (getattr(replied, "document", None) or getattr(replied, "video", None))
        if not media:
            await reply(
                message,
                "Reply to a file with <code>/genlink</code>. Two numbers are "
                "optional: hours until it expires, and how many times it may be "
                "opened — <code>/genlink 48 5</code>. A file already in the vault "
                "is shared with <code>/share &lt;id&gt;</code>.",
            )
            return

        ttl_hours, max_uses, problem = _limits(_args(message)[1:], "genlink")
        if problem:
            await reply(message, problem)
            return

        owner = message.from_user.id
        try:
            source = await replied.download()
            stored = ctx.storage.save_path(owner, source, name=media.file_name or "file.bin")
        except Exception as exc:  # noqa: BLE001 - quota and IO errors reach the user
            logger.warning("genlink save unconfirmed (%s)", type(exc).__name__)
            await reply(
                message,
                f"Could not confirm that save ({type(exc).__name__}). Check /files before retrying.",
            )
            return

        await _grant(client, message, stored, ttl_hours, max_uses, source="/genlink")

    async def links(_client, message):
        parts = _args(message)[1:]
        if len(parts) > 1 or (parts and (not parts[0].isascii() or not parts[0].isdecimal() or len(parts[0]) > 8 or int(parts[0]) < 1)):
            await reply(message, "Usage: <code>/links [page]</code>, starting at page 1.")
            return
        page = int(parts[0]) if parts else 1
        owner = message.from_user.id
        records = ctx.links.owned(owner)
        pages = max(1, (len(records) + 9) // 10)
        if page > pages:
            await reply(message, f"Choose a links page from 1 to {pages}.")
            return
        if not records:
            await reply(
                message,
                "You have no links yet. Reply to a file with <code>/genlink</code>.",
            )
            return

        rows = []
        for record in records[(page - 1) * 10:page * 10]:
            state = (
                "revoked"
                if record.revoked
                else "expired"
                if record.expired
                else "used up"
                if record.exhausted
                else "live"
            )
            file = ctx.storage.get(record.file_id)
            name = file.name if file else "file unavailable"
            rows.append(
                (
                    state,
                    name,
                    _uses_text(record),
                    f"in {_hours_left(record):.0f}h" if not record.expired else "—",
                )
            )
        live = sum(
            1
            for record in records
            if not (record.revoked or record.expired or record.exhausted)
        )
        navigation = []
        if page > 1:
            navigation.append(f"<code>/links {page - 1}</code> previous")
        if page < pages:
            navigation.append(f"<code>/links {page + 1}</code> next")
        await reply(
            message,
            panel(
                "Your links",
                icon=ctx.theme.emoji("link"),
                subtitle=(
                    f"{ctx.theme.emoji('diamond')} Page <b>{page}/{pages}</b> · <b>{len(records)}</b> link(s), <b>{live}</b> still live, newest first."
                ),
                table=Table(
                    headers=("State", "File", "Uses", "Expires"),
                    rows=tuple(rows),
                    aligns=("left", "left", "left", "right"),
                    max_column=26,
                    total_width=54,
                ),
                lines=[" · ".join(navigation)] if navigation else [],
                note="Revoke one with <code>/revoke &lt;token&gt;</code> or its own button.",
                footer="Tokens are hidden here. Lists are visible in this chat; use private chat for sensitive filenames.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def revoke(_client, message):
        parts = _args(message)
        if len(parts) != 2:
            await reply(message, "Usage: <code>/revoke &lt;token&gt;</code>")
            return
        owner = message.from_user.id
        try:
            record = ctx.links.resolve(parts[1].strip())
        except LinkError as exc:
            # A revoked token must still be revocable-by-owner idempotently;
            # anything else is a genuine failure.
            if str(exc) == "link revoked":
                await reply(message, "That link is already revoked.")
            else:
                await reply(message, f"Invalid link: {html.escape(str(exc))}")
            return

        if ctx.links.revoke(record.token, owner_id=owner):
            await reply(message, panel("Link revoked", icon=ctx.theme.emoji("check"),
                lines=["Link revoked. Future redemptions are blocked."],
                note="Already delivered files and in-flight deliveries are not erased.", footer="/links"))
        else:
            await reply(message, "That link does not belong to you.")

    # -- redemption: /start link_<token> -----------------------------------
    async def redeem(client, message, token: str):
        """Send the file behind *token*, or say precisely why it cannot be sent."""
        try:
            record = ctx.links.resolve(token)
        except LinkError as exc:
            reason = {
                "link revoked": "The owner revoked this link.",
                "link expired": "This link has expired.",
                "link used up": "This link has been opened as often as it allows.",
                "bad signature": "This link was not created by this bot.",
            }.get(str(exc), "This link is not valid.")
            logger.info("link refused (%s) for %s", exc, getattr(message.from_user, "id", None))
            await _refused(message, reason)
            return

        stored = ctx.storage.get(record.file_id)
        if stored is None:
            logger.warning("link %s… points at a missing file", record.token[:12])
            await _refused(message, "The file behind this link is no longer stored.")
            return

        # No use is spent for a missing metadata entry. Consume immediately
        # before delivery, with a second expiry/revocation/cap check.
        try:
            record = ctx.links.consume(token)
        except LinkError:
            await _refused(message, "This link is no longer available.")
            return

        caption = (
            f"<b>{html.escape(stored.name)}</b>\n"
            f"<code>{stored.size:,} bytes</code> · {_uses_text(record)}"
        )
        # Cached file_id first: a link opened on a freshly deployed instance still
        # works, because Telegram holds the bytes rather than this host.
        delivered = await send_stored(message, ctx.storage, stored, caption=caption)
        if not delivered:
            logger.info("link %s… could not deliver %s", record.token[:12], stored.name)
            return
        if getattr(ctx, "events", None) is not None:
            ctx.events.emit("link:redeem", uses=record.uses)
        logger.info(
            "link redeemed by %s (%s uses)",
            getattr(message.from_user, "id", None),
            record.uses,
        )

    async def _refused(message, reason: str) -> None:
        await reply(
            message,
            panel(
                "Link unavailable",
                icon=ctx.theme.emoji("lock"),
                subtitle=html.escape(reason),
                lines=["Ask whoever shared it for a fresh link."],
                footer="<code>/help</code> lists what this bot can do.",
            ),
            reply_markup=nav_keyboard(),
        )

    # -- the revoke button on the share card ------------------------------
    async def on_link_press(client, query, rest: str):
        parts = (rest or "").split(":", 1)
        action = parts[0].strip().lower() if parts else ""
        token = parts[1].strip() if len(parts) > 1 else ""
        if action != "revoke" or not token:
            await query.answer("That button is stale.", show_alert=True)
            return
        presser = getattr(getattr(query, "from_user", None), "id", None)
        try:
            record = ctx.links.resolve(token)
        except LinkError as exc:
            await query.answer(f"Nothing to revoke: {exc}.", show_alert=True)
            return
        if presser is None or record.owner_id != int(presser):
            await query.answer("Only the owner of this link can revoke it.", show_alert=True)
            return
        ctx.links.revoke(token, owner_id=int(presser))
        stored = ctx.storage.get(record.file_id)
        username = await _username(client)
        text, keyboard = _panel(record, stored, username)
        try:
            await rich_ui.edit(query, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - a stale card is not a failed revoke
            logger.debug("could not redraw the share card", exc_info=True)
        if getattr(ctx, "events", None) is not None:
            ctx.events.emit("link:revoke", by=presser)
        logger.info("link revoked from its card by %s", presser)
        await query.answer("Revoked: the link no longer delivers.")

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(f"{PREFIX}:x"):
        router.register(PREFIX, on_link_press)

    deep = getattr(ctx, "deeplinks", None)
    if deep is not None and not deep.handles(f"{DEEP_PREFIX}_x"):
        deep.register(DEEP_PREFIX, redeem)

    logger.info("Linkshare wired (share links redeem through /start %s_…)", DEEP_PREFIX)
    def identified(handler):
        async def wrapped(client, message):
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                await reply(message, "Use your personal Telegram user identity for link commands.")
                return
            return await handler(client, message)
        return wrapped

    handlers = {
        "genlink": genlink,
        "share": share,
        "links": links,
        "revoke": revoke,
    }
    return MANIFEST, {name: identified(handler) for name, handler in handlers.items()}
