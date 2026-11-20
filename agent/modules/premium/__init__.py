"""Premium — the tier, its allowances, and the owner commands that grant it.

``/premium`` shows the caller's tier, today's usage and what a raise would buy;
``/addpremium``, ``/delpremium`` and ``/premiumusers`` are owner-only, and
lifetime is ``/addpremium <id> 0``. Nothing here is a badge: the same numbers
are enforced by the filestore and the leech module.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from pyrogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from ...platform.manifest import PluginManifest
from ...platform.premium import TIERS
from ...platform.entitlements import EntitlementError
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply
from .limits import pitch, rows, until_text, usage_rows

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=False,
    slug="premium",
    name="Premium",
    version="1.0.0",
    description="Owner-granted premium that raises the real vault and daily limits.",
    commands=("premium", "myplan", "plans", "addpremium", "delpremium", "premiumusers"),
    permissions=("messages.read", "messages.send"),
    scope="all",
)

OWNER_ONLY = "This command is reserved for the bot owner."
DEFAULT_DAYS = 30
MAX_DAYS = 3650


def _parse_user(message, token: str | None) -> int | None:
    """A user id from the argument, or from the message being replied to."""
    if token:
        if token.isascii() and token.isdecimal() and len(token) <= 19:
            value = int(token)
            if 0 < value <= 9223372036854775807:
                return value
        return None
    replied = getattr(message, "reply_to_message", None)
    user = getattr(replied, "from_user", None) if replied is not None else None
    value = getattr(user, 'id', None)
    return value if type(value) is int and 0 < value <= 9223372036854775807 else None


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
        await book.ais_premium(user.id)
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
                footer=f'Your user ID: {user.id} · Counters reset at midnight UTC.',
            ),
            reply_markup=Keyboard([
                [Button('Compare plans', callback_data='prem:plans'), Button('Refresh my plan', callback_data='prem:status')],
                [Button('How to activate Premium', callback_data='prem:activate')],
                [Button('‹ Main menu', callback_data='menu:home')],
            ]),
        )
        logger.info("premium status user=%s premium=%s", user.id, book.is_premium(user.id))

    async def premium_press(client, query, rest):
        user = getattr(query, 'from_user', None)
        origin = getattr(query, 'message', None)
        if user is None or origin is None:
            await query.answer('Open /premium privately.', show_alert=True)
            return
        # Only the actual caller can view their own plan; never bot-message author.
        if getattr(getattr(origin, 'chat', None), 'id', None) != user.id:
            await query.answer('Open /premium in a private chat for plan options.', show_alert=True)
            return
        message = SimpleNamespace(from_user=user, chat=origin.chat, reply=origin.reply)
        try:
            if rest == 'status':
                await premium(client, message)
            elif rest == 'plans':
                await plans(client, message)
            elif rest == 'activate':
                owner = ctx.settings.owner_id
                lines = ['Premium is granted by this bot’s configured Owner. No checkout or payment collection is enabled here.',
                         f'Your Telegram ID: <code>{user.id}</code>.',
                         'Premium applies only to this bot. Creating and starting clones requires Premium, including for Owner and sudo.']
                if owner is not None and user.id == int(owner):
                    lines += [f'You are the configured Owner. Grant yourself one test day: <code>/addpremium {user.id} 1</code>.',
                              'Use 0 days only for an intentional lifetime grant. /premiumusers lists current grants.']
                else:
                    lines += ['Ask this bot’s Owner to grant your user ID Premium. Never send your bot token or account session to buy a plan.']
                await reply(message, panel('Activate Premium', lines=lines), reply_markup=Keyboard([
                    [Button('My plan', callback_data='prem:status')], [Button('‹ Main menu', callback_data='menu:home')]]))
            else:
                await query.answer('Unknown Premium option.', show_alert=True)
                return
            await query.answer()
        except Exception:
            logger.warning('#Errors Premium screen could not load')
            await query.answer('Premium status could not be confirmed. Check database availability; no grant was attempted.', show_alert=True)

    actions = getattr(ctx, 'actions', None)
    if actions is not None:
        actions.register('prem', premium_press)

    # -- /myplan -----------------------------------------------------------

    async def myplan(_client, message):
        """The short version of /premium: tier, what is left, nothing else."""
        user = getattr(message, "from_user", None)
        if user is None:
            return
        await book.ais_premium(user.id)
        tier = book.tier(user.id)
        rows = [row for row in usage_rows(book, user.id) if row[0] != "Tier"]
        await reply(
            message,
            panel(
                "Your plan",
                icon=ctx.theme.emoji("crown"),
                subtitle=f"<b>{tier.label}</b> — {until_text(book.until(user.id))}.",
                table=kv_table(rows),
                note="<code>/plans</code> compares the two tiers; <code>/premium</code> shows the full table.",
            ),
            reply_markup=nav_keyboard(),
        )

    # -- /plans ------------------------------------------------------------

    async def plans(_client, message):
        """What a raise actually buys, in one table."""
        await reply(
            message,
            panel(
                "Plans",
                icon=ctx.theme.emoji("star"),
                subtitle="Higher file and daily allowances · Premium-only clone creation and starts.",
                table=Table(headers=("Allowance", "Free → Premium"), rows=tuple(rows())),
                note=pitch(),
                footer="Owners grant premium with <code>/addpremium &lt;id&gt; [days]</code>.",
            ),
            reply_markup=nav_keyboard(),
        )

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
        if len(parts) > 3 or (len(parts) > 2 and (
                not parts[2].isascii() or not parts[2].isdecimal() or len(parts[2]) > 4 or int(parts[2]) > MAX_DAYS)):
            await reply(message, f'Days must be a whole number from 0 to {MAX_DAYS}; 0 means lifetime. No Premium was changed.')
            return
        if len(parts) > 2:
            days = int(parts[2])
        try:
            until = await book.agrant(target, days, by=message.from_user.id)
        except EntitlementError as exc:
            await reply(message, str(exc))
            return
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
        try:
            removed = await book.arevoke(target)
        except EntitlementError as exc:
            await reply(message, str(exc))
            return
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
        try:
            entries = await book.alisting()
        except EntitlementError as exc:
            await reply(message, str(exc))
            return
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
                "active" if entry.get("until") is None or entry["until"] > now else "expired",
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
        "myplan": myplan,
        "plans": plans,
        "addpremium": addpremium,
        "delpremium": delpremium,
        "premiumusers": premiumusers,
    }
