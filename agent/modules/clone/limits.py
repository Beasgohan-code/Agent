"""How many clones a member may run, and why that number is not magic.

A clone is a whole second bot: its own polling loop, its own session and its own
disk. One is free because one is useful; three is what premium buys, and the
deployment's own ceiling (``CLONE_LIMIT``) still caps the total so a busy
server cannot be talked into running fifty pollers by fifty strangers.
"""

from __future__ import annotations

#: Clones a member may run without premium.
FREE = 1

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
        f"Free accounts run <b>{FREE}</b> clone; premium runs <b>{PREMIUM}</b>. "
        "<code>/premium</code> shows your tier."
    )
