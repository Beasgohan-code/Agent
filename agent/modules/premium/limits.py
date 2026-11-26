"""How the tiers are described to a member.

The numbers live in :mod:`agent.platform.premium`; this file only turns them into
rows and sentences. Keeping them apart means a panel can never quote a limit the
enforcement does not use.
"""

from __future__ import annotations

import time

from ...platform.premium import FREE, PREMIUM


def rows(free_spent: dict[str, int] | None = None) -> list[tuple[str, str]]:
    """Two-column rows: what changes, then free versus premium."""
    return [
        ("Vault quota", f"{FREE.quota_mb} MB → {PREMIUM.quota_mb} MB"),
        ("Transfers/day", f"{FREE.transfers_per_day} → {PREMIUM.transfers_per_day}"),
        ("Encodes/day", f"{FREE.encodes_per_day} → {PREMIUM.encodes_per_day}"),
    ]


def until_text(until: float | None, *, now: float | None = None) -> str:
    """``lifetime``, a date, or ``not premium``."""
    if until is None:
        return "not premium"
    if until <= 0:
        return "lifetime"
    moment = time.time() if now is None else now
    if until <= moment:
        return "expired"
    return time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(until))


def usage_rows(book, user_id: int, *, now: float | None = None) -> list[tuple[str, str]]:
    """Today's allowance, as the member can see it."""
    tier = book.tier(user_id, now=now)
    return [
        ("Tier", tier.label),
        ("Transfers left today", f"{book.remaining(user_id, 'leech', now=now)} / {tier.transfers_per_day}"),
        ("Encodes left today", f"{book.remaining(user_id, 'encode', now=now)} / {tier.encodes_per_day}"),
        ("Vault quota", f"{tier.quota_mb} MB"),
    ]


def pitch() -> str:
    """One sentence for the bottom of a limit panel."""
    return (
        "Premium raises file and daily allowances and is required to create or start clones, "
        "including for Owner and sudo. Owners grant it with <code>/addpremium</code>."
    )
