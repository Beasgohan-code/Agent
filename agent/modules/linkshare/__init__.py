"""Managed channel-invite Linkshare with legacy file redemption and revocation.

/genlink now exclusively uses verified channel-invite logic. File-link creation
and its old /share and /linkchannel command surfaces have been retired. Existing
file tokens, subscription policies, listing and revocation remain compatible.
"""

from __future__ import annotations

import html
import logging
import time

from pyrogram.enums import ButtonStyle
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
    group_compatible=False,
    clone_compatible=True,
    slug="linkshare",
    name="Linkshare",
    version="1.1.0",
    description="Managed channel invites; existing file-link access and revocation retained.",
    commands=("genlink", "links", "revoke"),
    permissions=("messages.read", "storage.read", "storage.write"),
)

#: Callback prefix for the share panel's buttons.
PREFIX = "link"

#: Deep-link prefix this module owns: ``/start link_<token>``.
DEEP_PREFIX = "link"

#: Extensions Telegram should show as a playable video rather than a document.
VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

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
            logger.debug("Could not read bot username")
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
                [ctx.theme.button("Copy link", icon="link", copy_text=url, style=ButtonStyle.SUCCESS)]
            )
        buttons.append(
            [
                ctx.theme.button(
                    "Revoke", icon="ban",
                    callback_data=f"{PREFIX}:revoke:{record.token}",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
        buttons.append(
            [ctx.theme.button("Menu", icon="back", callback_data="menu:home", style=ButtonStyle.PRIMARY)]
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

    from .subscription import build_channels
    genlink = build_channels(ctx)

    async def links(_client, message):
        parts = _args(message)[1:]
        if len(parts) > 1 or (parts and (not parts[0].isascii() or not parts[0].isdecimal() or len(parts[0]) > 8 or int(parts[0]) < 1)):
            await reply(message, "Usage: <code>/links [page]</code>, starting at page 1.")
            return
        page = int(parts[0]) if parts else 1
        owner = message.from_user.id
        records = await ctx.links.aowned(owner)
        pages = max(1, (len(records) + 9) // 10)
        if page > pages:
            await reply(message, f"Choose a links page from 1 to {pages}.")
            return
        if not records:
            await reply(
                message,
                "You have no legacy file links. Use /settings for channel management and /genlink ID for channel invites.",
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
            record = await ctx.links.aresolve(parts[1].strip())
        except LinkError as exc:
            # A revoked token must still be revocable-by-owner idempotently;
            # anything else is a genuine failure.
            if str(exc) == "link revoked":
                await reply(message, "That link is already revoked.")
            else:
                await reply(message, f"Invalid link: {html.escape(str(exc))}")
            return

        if await ctx.links.arevoke(record.token, owner_id=owner):
            await reply(message, panel("Link revoked", icon=ctx.theme.emoji("check"),
                lines=["Link revoked. Future redemptions are blocked."],
                note="Already delivered files and in-flight deliveries are not erased.", footer="/links"))
        else:
            await reply(message, "That link does not belong to you.")

    # -- redemption: /start link_<token> -----------------------------------
    async def redeem(client, message, token: str):
        """Send the file behind *token*, or say precisely why it cannot be sent."""
        try:
            record = await ctx.links.aresolve(token)
        except LinkError as exc:
            reason = {
                "link revoked": "The owner revoked this link.",
                "link expired": "This link has expired.",
                "link used up": "This link has been opened as often as it allows.",
                "bad signature": "This link was not created by this bot.",
            }.get(str(exc), "This link is not valid.")
            logger.info("Share link refused")
            await _refused(message, reason)
            return

        from .subscription import allowed as subscription_allowed
        if not await subscription_allowed(ctx, client, message):
            return

        stored = ctx.storage.get(record.file_id)
        if stored is None:
            logger.warning("Share link points at missing file metadata")
            await _refused(message, "The file behind this link is no longer stored.")
            return

        # No use is spent for a missing metadata entry. Consume immediately
        # before delivery, with a second expiry/revocation/cap check.
        try:
            mid = getattr(message, "id", None)
            uid = getattr(getattr(message, "from_user", None), "id", None)
            chat = getattr(getattr(message, "chat", None), "id", None)
            if type(mid) is not int or mid <= 0 or type(uid) is not int or uid <= 0 or type(chat) is not int:
                raise LinkError("Invalid redemption request identity")
            record = await ctx.links.aconsume(token, request_id=f"{chat}:{uid}:{mid}")
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
            logger.info("Share link delivery was not confirmed")
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
            record = await ctx.links.aresolve(token)
        except LinkError as exc:
            await query.answer(f"Nothing to revoke: {exc}.", show_alert=True)
            return
        if presser is None or record.owner_id != int(presser):
            await query.answer("Only the owner of this link can revoke it.", show_alert=True)
            return
        await ctx.links.arevoke(token, owner_id=int(presser))
        stored = ctx.storage.get(record.file_id)
        username = await _username(client)
        text, keyboard = _panel(record, stored, username)
        try:
            await rich_ui.edit(query, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - a stale card is not a failed revoke
            logger.debug("Could not redraw share card")
        if getattr(ctx, "events", None) is not None:
            ctx.events.emit("link:revoke", by=presser)
        logger.info("link revoked from its card by %s", presser)
        await query.answer("Revoked: the link no longer delivers.")

    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(f"{PREFIX}:x"):
        router.register(PREFIX, on_link_press)

    if router is not None and not router.handles("chset:page:0"):
        from .subscription import build_controls
        router.register("chset", build_controls(ctx))

    deep = getattr(ctx, "deeplinks", None)
    if deep is not None and not deep.handles(f"{DEEP_PREFIX}_x"):
        deep.register(DEEP_PREFIX, redeem)

    if deep is not None and not deep.handles("channel_x"):
        from .subscription import redeem_channel

        async def open_channel(client, message, token):
            return await redeem_channel(ctx, client, message, token)

        deep.register("channel", open_channel)

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
        "links": links,
        "revoke": revoke,
    }
    manifest = MANIFEST
    registry = getattr(ctx, "registry", None)
    if registry is not None:
        # FileStore builds first. Use actual registered ownership, including
        # safe fallback when that optional module failed to build.
        has_batch_owner = any("batch" in item.commands for item in registry.manifests())
    else:
        selected = tuple(ctx.settings.plugins or ())
        has_batch_owner = selected == ("*",) or "filestore" in selected
    if not has_batch_owner:
        from dataclasses import replace
        handlers["batch"] = genlink
        manifest = replace(MANIFEST, commands=(*MANIFEST.commands, "batch"))
    return manifest, {name: identified(handler) for name, handler in handlers.items()}


def extra_handlers(ctx):
    """Runtime-owned watcher: disabling Linkshare detaches/gates approval too."""
    from pyrogram.handlers import ChatJoinRequestHandler
    from .subscription import approve_request

    async def on_request(client, update):
        await approve_request(ctx, client, update)

    return [ChatJoinRequestHandler(on_request)]
