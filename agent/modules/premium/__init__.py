"""Premium — Videl1's tier, with allowances this bot actually enforces.

Videl1 sells premium; here it is granted by the owner (``/addpremium``) and it
buys exactly three things: a bigger vault, more transfers per day and more
encodes per day. Those are the numbers in :mod:`agent.platform.premium`, and
``filestore`` and ``leech`` read them before they spend anything — a tier that
changed a badge and no limit would be a fake feature.

Lifetime is ``/addpremium <id> 0``, the same spelling Videl1 uses.
"""

from __future__ import annotations

import logging
import time

from ...platform.manifest import PluginManifest
from ...platform.premium import TIERS
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply
from .limits import pitch, rows, until_text, usage_rows

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="premium",
    name="Premium",
    version="1.0.0",
    description="Owner-granted premium that raises the real vault and daily limits.",
    commands=("premium", "addpremium", "delpremium", "premiumusers"),
    permissions=("messages.read", "messages.send"),
    scope="all",
)

OWNER_ONLY = "This command is reserved for the bot owner."
DEFAULT_DAYS = 30
MAX_DAYS = 3650


def _parse_user(message, token: str | None) -> int | None:
    """A user id from the argument, or from the message being replied to."""
    if token:
        cleaned = token.lstrip("-")
        if cleaned.isdigit():
            return int(token)
    replied = getattr(message, "reply_to_message", None)
    user = getattr(replied, "from_user", None) if replied is not None else None
    return int(user.id) if user is not None and getattr(user, "id", None) else None


def build(ctx):
    book = ctx.premium

    async def _owner(client, message) -> bool:
        owner_id = ctx.settings.owner_id
        user = getattr(message, "from_user", None)
        if owner_id is None:
            await reply(
                message,
                "No <code>OWNER_ID</code> is set, so nobody can grant premium. "
                "Set it and restart.",
            )
            return False
        if user is None or int(user.id) != int(owner_id):
            await reply(message, OWNER_ONLY)
            return False
        return True

    # -- /premium ----------------------------------------------------------

    async def premium(client, message):
        user = getattr(message, "from_user", None)
        if user is None:
            return
        until = book.until(user.id)
        await reply(
            message,
            panel(
                "Premium",
                icon=ctx.theme.emoji("sparkles"),
                subtitle=f"You are on <b>{book.tier(user.id).label}</b> — {until_text(until)}.",
                table=Table(headers=("Allowance", "Free → Premium"), rows=tuple(rows())),
                lines=[
                    "Today: "
                    + ", ".join(
                        f"{label} <b>{value}</b>"
                        for label, value in usage_rows(book, user.id)[1:]
                    )
                    + "."
                ],
                note=pitch(),
                footer="Counters reset at midnight UTC.",
            ),
            reply_markup=nav_keyboard(),
        )
        logger.info("premium status user=%s premium=%s", user.id, book.is_premium(user.id))

    # -- /addpremium -------------------------------------------------------

    async def addpremium(client, message):
        if not await _owner(client, message):
            return
        parts = (getattr(message, "text", "") or "").split()
        target = _parse_user(message, parts[1] if len(parts) > 1 else None)
        if target is None:
            await reply(
                message,
                "Usage: <code>/addpremium &lt;user_id&gt; [days]</code> — reply to a "
                "member to use their id, and <code>0</code> days means lifetime.",
            )
            return
        days = DEFAULT_DAYS
        if len(parts) > 2 and parts[2].isdigit():
            days = max(0, min(MAX_DAYS, int(parts[2])))
        until = book.grant(target, days, by=message.from_user.id)
        events = getattr(ctx, "events", None)
        if events is not None:
            events.emit("premium:grant", user=target, days=days, by=message.from_user.id)
        await reply(
            message,
            panel(
                "Premium granted",
                icon=ctx.theme.emoji("check"),
                table=kv_table(
                    [
                        ("User", f"<code>{target}</code>"),
                        ("Until", until_text(until)),
                        ("Vault quota", f"{book.tier(target).quota_mb} MB"),
                    ]
                ),
                footer="They can check it with <code>/premium</code>.",
            ),
        )
        try:
            await client.send_message(
                target,
                f"<b>Premium is active</b> until {until_text(until)}. "
                "Your vault and daily limits went up; <code>/premium</code> shows them.",
            )
        except Exception:  # noqa: BLE001 - the grant stands even if the DM fails
            logger.info("could not notify user %s about premium", target)

    # -- /delpremium -------------------------------------------------------

    async def delpremium(client, message):
        if not await _owner(client, message):
            return
        parts = (getattr(message, "text", "") or "").split()
        target = _parse_user(message, parts[1] if len(parts) > 1 else None)
        if target is None:
            await reply(message, "Usage: <code>/delpremium &lt;user_id&gt;</code>")
            return
        removed = book.revoke(target)
        events = getattr(ctx, "events", None)
        if events is not None and removed:
            events.emit("premium:revoke", user=target, by=message.from_user.id)
        await reply(
            message,
            f"Premium removed from <code>{target}</code>."
            if removed
            else f"<code>{target}</code> had no premium.",
        )

    # -- /premiumusers -----------------------------------------------------

    async def premiumusers(client, message):
        if not await _owner(client, message):
            return
        entries = book.listing()
        if not entries:
            await reply(
                message,
                panel(
                    "Premium users",
                    icon=ctx.theme.emoji("stats"),
                    lines=["Nobody has premium yet."],
                    footer="<code>/addpremium &lt;user_id&gt; [days]</code> grants it.",
                ),
            )
            return
        now = time.time()
        table_rows = tuple(
            (
                str(entry["user_id"]),
                until_text(entry.get("until"), now=now) if entry.get("until") is not None else "lifetime",
                "active" if book.is_premium(entry["user_id"], now=now) else "expired",
            )
            for entry in entries
        )
        await reply(
            message,
            panel(
                "Premium users",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"<b>{len(entries)}</b> recorded (newest first).",
                table=Table(headers=("User", "Until", "State"), rows=table_rows),
                footer="Expiry is checked on use, not on a timer.",
            ),
            reply_markup=nav_keyboard(),
        )

    logger.info("premium plugin wired with %d tier(s), %d premium user(s)", len(TIERS), book.count())
    return MANIFEST, {
        "premium": premium,
        "addpremium": addpremium,
        "delpremium": delpremium,
        "premiumusers": premiumusers,
    }
