"""Agent — single-instance lease, so one bot token is served by one process.

* a copy takes the lease when it is absent, expired, or already ours;
* a heartbeat renews it; a copy that loses it stops instead of double-serving;
* shutdown releases it so the next deploy starts immediately;
* ``/restart`` releases it before exiting, so the replacement starts at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

TTL = 60.0
BEAT = 15.0
POLL = 5.0


def default_owner() -> str:
    """Stable-ish identity for this process."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class InstanceLease:
    """A file-backed lease that only one process at a time may hold."""

    def __init__(
        self,
        path: Path,
        *,
        owner: str | None = None,
        ttl: float = TTL,
        beat: float = BEAT,
    ) -> None:
        self.path = Path(path)
        self.owner = owner or default_owner()
        self.ttl = ttl
        self.beat = beat
        self.held = False
        self.other: str | None = None
        #: Set when the lease file cannot be written; the bot runs unprotected.
        self.degraded = False
        self._task: asyncio.Task | None = None

    # -- state -------------------------------------------------------------

    def read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def state(self) -> dict:
        current = self.read() or {}
        return {
            "owner": current.get("owner"),
            "held_by_us": self.held,
            "degraded": self.degraded,
            "mine": self.owner,
            "expires_in": max(0.0, round(float(current.get("until", 0)) - time.time(), 1)),
            "host": current.get("host"),
            "pid": current.get("pid"),
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner": self.owner,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "until": time.time() + self.ttl,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)

    def _is_free(self) -> bool:
        current = self.read()
        if not current:
            return True
        if current.get("owner") == self.owner:
            return True
        return float(current.get("until", 0)) <= time.time()

    # -- lifecycle ---------------------------------------------------------

    def try_acquire(self) -> bool:
        """Take the lease if it is free, expired, or already ours."""
        if self._is_free():
            try:
                self._write()
            except OSError as exc:
                # A read-only data directory is a deployment problem, not a
                # reason to refuse to serve. Say so once and keep going.
                if not self.degraded:
                    logger.warning(
                        "Cannot write the instance lease at %s (%s). Continuing "
                        "without single-instance protection: overlapping deploys "
                        "could double-serve updates.",
                        self.path,
                        exc,
                    )
                self.degraded = True
                self.held = False
                return True
            self.held = True
            self.other = None
            try:
                os.chmod(self.path, 0o600)
            except OSError:  # pragma: no cover - platform dependent
                pass
            return True
        self.other = (self.read() or {}).get("owner")
        return False

    async def acquire(self, *, wait_seconds: float = 90.0, poll: float = POLL) -> bool:
        """        Returning False is not an error: it means another copy is still live
                and this one must not serve updates.
                
        """
        deadline = time.monotonic() + max(0.0, wait_seconds)
        announced = False
        while True:
            if self.try_acquire():
                if announced:
                    logger.info("Instance lease acquired after waiting.")
                return True
            if not announced:
                logger.warning(
                    "Another instance holds the lease (%s); waiting up to %.0fs.",
                    self.other,
                    wait_seconds,
                )
                announced = True
            if time.monotonic() >= deadline:
                logger.error("Instance lease still held by %s; refusing to double-serve.", self.other)
                return False
            await asyncio.sleep(poll)

    def heartbeat(self) -> bool:
        """Renew if we still hold it. False means somebody else took over."""
        current = self.read()
        if current and current.get("owner") != self.owner:
            self.held = False
            self.other = current.get("owner")
            return False
        if self.held:
            try:
                self._write()
            except OSError:
                self.degraded = True
            return True
        return False

    def release(self) -> None:
        """Drop the lease so the next process can start immediately."""
        current = self.read()
        if current and current.get("owner") == self.owner:
            try:
                self.path.unlink()
            except OSError:  # pragma: no cover
                pass
        self.held = False

    async def run_heartbeat(self, stop_event: asyncio.Event) -> None:
        """Renew on a timer; stop the bot if another copy has taken over."""
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.beat)
                return
            except asyncio.TimeoutError:
                pass
            if not self.heartbeat():
                logger.critical("Instance lease was taken over by %s; stopping.", self.other)
                stop_event.set()
                return

    def start_heartbeat(self, stop_event: asyncio.Event) -> asyncio.Task:
        self._task = asyncio.create_task(
            self.run_heartbeat(stop_event), name="agent-instance-heartbeat"
        )
        return self._task

    async def stop_heartbeat(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
