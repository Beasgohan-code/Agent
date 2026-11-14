"""Agent — the premium tier: its numbers, and where they are stored.

Both columns are enforced, not advertised:

===================  ==========  =========
Allowance            free        premium
===================  ==========  =========
vault quota          64 MiB      256 MiB
transfers per day    5           50
encodes per day      3           25
===================  ==========  =========

State is JSON on disk next to the other stores: ``until`` in epoch seconds, or
``None`` for lifetime. Daily counters carry the UTC date they belong to, so an
allowance resets at midnight UTC without a scheduler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .db import load_document, save_document

logger = logging.getLogger(__name__)

DAY = 86400


@dataclass(frozen=True)
class Tier:
    """What one tier is allowed."""

    slug: str
    label: str
    quota_mb: int
    transfers_per_day: int
    encodes_per_day: int

    @property
    def quota_bytes(self) -> int:
        return self.quota_mb * 1024 * 1024


FREE = Tier("free", "Free", 64, 5, 3)
PREMIUM = Tier("premium", "Premium", 256, 50, 25)
TIERS = (FREE, PREMIUM)


def tier_for(premium: bool) -> Tier:
    return PREMIUM if premium else FREE


def _today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() if now is None else now))


class PremiumBook:
    """Who has premium, and how much of today's allowance they have spent."""

    def __init__(self, root: Path, *, db=None) -> None:
        self._path = Path(root) / "premium.json"
        self._db = db
        self._data: dict = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict:
        data = load_document(self._db, "premium", self._path, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("users", {})
        data.setdefault("usage", {})
        return data

    def _save(self) -> None:
        save_document(self._db, "premium", self._path, self._data)

    def hydrate(self) -> None:
        """Re-read the ledger; called once PostgreSQL has been loaded."""
        self._data = self._load()

    # -- membership --------------------------------------------------------

    def record(self, user_id: int) -> dict | None:
        return self._data["users"].get(str(int(user_id)))

    def is_premium(self, user_id: int, *, now: float | None = None) -> bool:
        entry = self.record(user_id)
        if entry is None:
            return False
        until = entry.get("until")
        if until is None:
            return True
        return float(until) > (time.time() if now is None else now)

    def until(self, user_id: int) -> float | None:
        """Epoch seconds, ``0.0`` for lifetime, or ``None`` when not premium."""
        entry = self.record(user_id)
        if entry is None:
            return None
        until = entry.get("until")
        return 0.0 if until is None else float(until)

    def tier(self, user_id: int, *, now: float | None = None) -> Tier:
        return tier_for(self.is_premium(user_id, now=now))

    def grant(
        self,
        user_id: int,
        days: int = 30,
        *,
        by: int | None = None,
        now: float | None = None,
    ) -> float | None:
        """Give premium for *days* (0 = lifetime). Returns the new expiry."""
        moment = time.time() if now is None else now
        current = self.record(user_id) or {}
        if days <= 0:
            until: float | None = None
        else:
            base = max(moment, float(current.get("until") or 0) if current.get("until") else moment)
            until = base + days * DAY
        self._data["users"][str(int(user_id))] = {
            "until": until,
            "since": current.get("since", moment),
            "granted_at": moment,
            "by": by,
        }
        self._save()
        logger.info("premium granted user=%s days=%s by=%s", user_id, days or "lifetime", by)
        return until

    def revoke(self, user_id: int) -> bool:
        removed = self._data["users"].pop(str(int(user_id)), None)
        if removed is not None:
            self._save()
            logger.info("premium revoked user=%s", user_id)
        return removed is not None

    def listing(self, limit: int = 50) -> list[dict]:
        items = [
            {"user_id": int(uid), **entry}
            for uid, entry in self._data["users"].items()
            if str(uid).lstrip("-").isdigit()
        ]
        items.sort(key=lambda item: item.get("granted_at") or 0, reverse=True)
        return items[: max(0, limit)]

    def count(self) -> int:
        return len(self._data["users"])

    # -- daily allowances --------------------------------------------------

    def usage(self, user_id: int, kind: str, *, now: float | None = None) -> int:
        bucket = self._data["usage"].get(str(int(user_id))) or {}
        if bucket.get("day") != _today(now):
            return 0
        return int(bucket.get(kind, 0))

    def remaining(self, user_id: int, kind: str, *, now: float | None = None) -> int:
        tier = self.tier(user_id, now=now)
        limit = _limit(tier, kind)
        return max(0, limit - self.usage(user_id, kind, now=now))

    def take(self, user_id: int, kind: str, *, now: float | None = None) -> bool:
        """Spend one unit of *kind*; False when today's allowance is gone."""
        moment = time.time() if now is None else now
        tier = self.tier(user_id, now=moment)
        limit = _limit(tier, kind)
        key = str(int(user_id))
        bucket = self._data["usage"].get(key) or {}
        if bucket.get("day") != _today(moment):
            bucket = {"day": _today(moment)}
        spent = int(bucket.get(kind, 0))
        if spent >= limit:
            return False
        bucket[kind] = spent + 1
        self._data["usage"][key] = bucket
        self._save()
        return True

    def reset_usage(self) -> None:
        self._data["usage"] = {}
        self._save()


def _limit(tier: Tier, kind: str) -> int:
    if kind == "leech":
        return tier.transfers_per_day
    if kind == "encode":
        return tier.encodes_per_day
    raise ValueError(f"unknown allowance {kind!r}")
