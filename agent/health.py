"""Agent — liveness bookkeeping.

A tiny, dependency-free state machine that records how the Telegram link is
behaving. It never decides policy on its own; :mod:`agent.watchdog` probes,
this module remembers, and the health endpoint reports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

HEALTHY = "healthy"
DEGRADED = "degraded"
DOWN = "down"
STARTING = "starting"


@dataclass(frozen=True)
class HealthSnapshot:
    """Point-in-time view of the bot's health."""

    state: str
    uptime_seconds: float
    probes: int
    failures: int
    consecutive_failures: int
    latency_ms: int | None
    seconds_since_ok: float | None
    seconds_since_activity: float | None
    last_error: str | None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "probes": self.probes,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "latency_ms": self.latency_ms,
            "seconds_since_ok": (
                None if self.seconds_since_ok is None else round(self.seconds_since_ok, 1)
            ),
            "seconds_since_activity": (
                None
                if self.seconds_since_activity is None
                else round(self.seconds_since_activity, 1)
            ),
            "last_error": self.last_error,
        }


class HealthMonitor:
    """Records probe outcomes and derives a health state.

    ``degraded_after`` / ``down_after`` are ages (in seconds) since the last
    successful probe. ``failure_threshold`` short-circuits: that many
    consecutive failures marks the bot down without waiting for the clock.
    """

    def __init__(
        self,
        *,
        degraded_after: float = 90.0,
        down_after: float = 300.0,
        failure_threshold: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._started = clock()
        self._degraded_after = degraded_after
        self._down_after = down_after
        self._failure_threshold = max(1, int(failure_threshold))

        self._probes = 0
        self._failures = 0
        self._consecutive_failures = 0
        self._last_ok: float | None = None
        self._last_activity: float | None = None
        self._latency_ms: int | None = None
        self._last_error: str | None = None

    # -- recording ---------------------------------------------------------

    def record_success(self, latency_ms: float | None = None) -> None:
        """A probe (or any successful Telegram call) succeeded."""
        self._probes += 1
        self._last_ok = self._clock()
        self._consecutive_failures = 0
        if latency_ms is not None:
            self._latency_ms = max(0, int(latency_ms))

    def record_failure(self, reason: str) -> None:
        """A probe failed. Counts toward the threshold and the last error."""
        self._probes += 1
        self._failures += 1
        self._consecutive_failures += 1
        self._last_error = (reason or "unknown error").strip()[:300]

    def record_activity(self, source: str = "update") -> None:
        """Something from Telegram actually arrived (informational only)."""
        self._last_activity = self._clock()

    # -- derived -----------------------------------------------------------

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, self._clock() - self._started)

    def state(self) -> str:
        now = self._clock()

        if self._consecutive_failures >= self._failure_threshold:
            return DOWN
        if self._last_ok is None:
            # Nothing has succeeded yet: still booting unless we are failing.
            return DEGRADED if self._consecutive_failures else STARTING

        age = now - self._last_ok
        if age >= self._down_after:
            return DOWN
        if age >= self._degraded_after or self._consecutive_failures:
            return DEGRADED
        return HEALTHY

    def snapshot(self) -> HealthSnapshot:
        now = self._clock()
        return HealthSnapshot(
            state=self.state(),
            uptime_seconds=self.uptime_seconds,
            probes=self._probes,
            failures=self._failures,
            consecutive_failures=self._consecutive_failures,
            latency_ms=self._latency_ms,
            seconds_since_ok=None if self._last_ok is None else max(0.0, now - self._last_ok),
            seconds_since_activity=(
                None if self._last_activity is None else max(0.0, now - self._last_activity)
            ),
            last_error=self._last_error,
        )
