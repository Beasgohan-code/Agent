"""How many clones a member may run, and why that number is not magic.

Creation requires bot premium, including for sudo and bot Owner users. The deployment ceiling
still applies to all users, and existing ineligible clones can be stopped/deleted
without granting permission to restart them.
"""

from __future__ import annotations

#: Free members cannot create or restart clones.
FREE = 0

#: Clones a premium member may run.
PREMIUM = 3


def allowance(premium, user_id: int | None) -> tuple[int, str]:
    """``(clones allowed, tier label)`` for one member.

    ``premium`` may be ``None`` (a build without the premium module), in which
    case everyone is on the free number instead of crashing.
    """
    if premium is None or user_id is None:
        return FREE, "free"
    try:
        if premium.is_premium(user_id):
            return PREMIUM, premium.tier(user_id).label
    except Exception:  # noqa: BLE001 - a broken ledger must not block /clone
        return FREE, "free"
    return FREE, "free"


def pitch() -> str:
    """The one sentence under the limit, said once."""
    return (
        f"Cloning requires bot premium, including for sudo and bot Owner users. Premium allows <b>{PREMIUM}</b> clones. "
        "<code>/premium</code> shows your tier."
    )
