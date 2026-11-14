"""Agent — watchdog.

Probes the Telegram link on a timer, records the outcome and, when the link
stays down beyond the tolerance, asks the supervisor for a restart.

Deliberate design choices (learned from Videl1 and Meikoagent):

* **No self-ping.** Nothing here calls the bot's own HTTP endpoint to fake
  traffic; probes are genuine Telegram API calls.
* **Recovery is observable.** Every probe is recorded, and state transitions
  are logged once, not on every tick.
* **Restart is the supervisor's job.** After ``fatal_after`` failed probes the
  process exits non-zero (Docker ``restart`` / Render restart policy). Trying
  to rebuild the client in-place risks two update streams.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .config import Settings
from .health import DEGRADED, DOWN, HEALTHY, STARTING, HealthMonitor

logger = logging.getLogger(__name__)


class Watchdog:
    """Periodic liveness probe for a running client."""

    def __init__(
        self,
        client,
        monitor: HealthMonitor,
        *,
        interval: float = 30.0,
        timeout: float = 20.0,
        fatal_after: int = 5,
        on_fatal=None,
    ) -> None:
        self._client = client
        self._monitor = monitor
        self._interval = max(0.01, float(interval))
        self._timeout = max(0.01, float(timeout))
        self._fatal_after = max(1, int(fatal_after))
        self._on_fatal = on_fatal
        self._last_state: str | None = None

    @property
    def monitor(self) -> HealthMonitor:
        return self._monitor

    async def probe(self) -> bool:
        """One liveness check. Returns ``True`` when Telegram answered."""
        started = time.perf_counter()
        try:
            if getattr(self._client, "is_connected", True) is False:
                # The socket dropped; re-establish it before pinging.
                await asyncio.wait_for(self._client.connect(), timeout=self._timeout)

            await asyncio.wait_for(self._client.get_me(), timeout=self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._monitor.record_failure(f"{type(exc).__name__}: {exc}")
            self._log_transition()
            return False

        self._monitor.record_success((time.perf_counter() - started) * 1000)
        self._log_transition()
        return True

    async def run(self, stop_event: asyncio.Event) -> None:
        """Probe until *stop_event* is set or the link is declared dead."""
        logger.info(
            "Watchdog started (interval=%.1fs, timeout=%.1fs, fatal_after=%d)",
            self._interval,
            self._timeout,
            self._fatal_after,
        )
        try:
            while not stop_event.is_set():
                await self.probe()

                if self._monitor.consecutive_failures >= self._fatal_after:
                    logger.critical(
                        "Telegram unreachable for %d consecutive probes; requesting restart.",
                        self._monitor.consecutive_failures,
                    )
                    if self._on_fatal is not None:
                        self._on_fatal()
                    return

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.debug("Watchdog cancelled.")
            raise
        finally:
            logger.info("Watchdog stopped.")

    # -- helpers -----------------------------------------------------------

    def _log_transition(self) -> None:
        state = self._monitor.state()
        if state == self._last_state:
            return
        self._last_state = state

        if state == HEALTHY:
            logger.info("Health: healthy (telegram reachable).")
        elif state == DEGRADED:
            logger.warning(
                "Health: degraded (%d consecutive failures, last error: %s).",
                self._monitor.consecutive_failures,
                self._monitor.snapshot().last_error,
            )
        elif state == DOWN:
            logger.error("Health: down (%d consecutive failures).", self._monitor.consecutive_failures)
        elif state == STARTING:
            logger.debug("Health: starting.")


def build_watchdog(client, monitor: HealthMonitor, settings: Settings, on_fatal=None) -> Watchdog:
    """Watchdog configured from validated settings."""
    return Watchdog(
        client,
        monitor,
        interval=settings.watchdog_interval,
        timeout=settings.watchdog_timeout,
        fatal_after=settings.watchdog_fatal_after,
        on_fatal=on_fatal,
    )
