"""Agent — what a worker is actually doing, as opposed to *whether* it is.

``is_running`` is a boolean standing in for a process, and it answers the wrong
question. It cannot tell "Telegram refused the token" from "it started and then
died", cannot say how many times we tried, and gives an owner nothing to act on.

This module replaces it with the states a long-lived client really passes
through, the transitions between them, and the bookkeeping an operator needs:
when the state began, how many attempts failed, and the last error in Telegram's
own words.

Nothing here talks to Telegram, so the whole lifecycle is testable without a
network — which is the point: state machines are where supervisors lie.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class State(StrEnum):
    """The states a worker can be in."""

    QUEUED = "queued"          # accepted, not started yet
    VALIDATING = "validating"  # token shape / Telegram handshake in progress
    STARTING = "starting"      # client connecting
    RUNNING = "running"        # answering updates
    DEGRADED = "degraded"      # connected, but something is wrong (no identity)
    STOPPING = "stopping"      # told to stop, teardown in flight
    STOPPED = "stopped"        # cleanly stopped on request
    FAILED = "failed"          # could not start, or died; ``last_error`` says why


#: States in which a client is holding a connection.
LIVE = (State.RUNNING, State.DEGRADED)

#: States that may be retried by the supervisor without human input.
RETRYABLE = (State.FAILED, State.DEGRADED)

#: Allowed transitions. A machine that accepts anything is a machine that hides
#: bugs, so an impossible move raises instead of being quietly absorbed.
TRANSITIONS: dict[State, tuple[State, ...]] = {
    State.QUEUED: (State.VALIDATING, State.STOPPED, State.FAILED),
    State.VALIDATING: (State.STARTING, State.FAILED, State.STOPPED),
    State.STARTING: (State.RUNNING, State.DEGRADED, State.FAILED, State.STOPPED),
    State.RUNNING: (State.STOPPING, State.DEGRADED, State.FAILED),
    State.DEGRADED: (State.RUNNING, State.STOPPING, State.FAILED, State.STARTING),
    State.STOPPING: (State.STOPPED, State.FAILED),
    State.STOPPED: (State.VALIDATING, State.STARTING),
    State.FAILED: (State.VALIDATING, State.STARTING, State.STOPPED),
}

#: How a state reads in a panel or a log line.
LABELS: dict[State, str] = {
    State.QUEUED: "⏳ Queued",
    State.VALIDATING: "🔍 Checking",
    State.STARTING: "🔄 Starting",
    State.RUNNING: "✅ Running",
    State.DEGRADED: "⚠️ Degraded",
    State.STOPPING: "⏹ Stopping",
    State.STOPPED: "⏸ Stopped",
    State.FAILED: "❌ Failed",
}


class LifecycleError(ValueError):
    """An illegal transition, e.g. ``failed -> running`` without a start."""


@dataclass
class WorkerState:
    """One worker's state plus the history an operator needs."""

    state: State = State.QUEUED
    since: float = field(default_factory=time.time)
    #: Consecutive failed starts; reset by a successful one.
    attempts: int = 0
    #: Telegram's (or the runtime's) last complaint, verbatim.
    last_error: str = ""
    #: The username Telegram reported, when it reports one.
    username: str = ""

    def move(self, target: State, *, error: str = "", now: float | None = None) -> "WorkerState":
        """Transition to *target*, or raise if that is not a real transition."""
        if target == self.state:
            return self
        allowed = TRANSITIONS.get(self.state, ())
        if target not in allowed:
            raise LifecycleError(
                f"{self.state.value} -> {target.value} is not a transition a worker can make"
            )
        self.state = target
        self.since = now if now is not None else time.time()
        if target in (State.FAILED, State.DEGRADED):
            self.attempts += 1
            self.last_error = error or self.last_error
        elif target == State.RUNNING:
            self.attempts = 0
            self.last_error = ""
        return self

    @property
    def live(self) -> bool:
        return self.state in LIVE

    @property
    def label(self) -> str:
        return LABELS.get(self.state, self.state.value.title())

    @property
    def uptime(self) -> float:
        """Seconds in the current state (``0`` before a clock exists)."""
        return max(0.0, time.time() - self.since)


class Registry:
    """Every worker's state, kept apart from the clients themselves.

    Deliberately dumb storage: the manager owns the connections, this owns what
    we say about them, so a client that dies without telling us still has a
    state someone can read.
    """

    def __init__(self) -> None:
        self._states: dict[int, WorkerState] = {}

    def __contains__(self, bot_id: object) -> bool:
        return int(bot_id) in self._states  # type: ignore[arg-type]

    def get(self, bot_id: int) -> WorkerState:
        return self._states.setdefault(int(bot_id), WorkerState())

    def move(self, bot_id: int, target: State, *, error: str = "") -> WorkerState:
        return self.get(bot_id).move(target, error=error)

    def set(self, bot_id: int, state: WorkerState) -> None:
        self._states[int(bot_id)] = state

    def forget(self, bot_id: int) -> None:
        self._states.pop(int(bot_id), None)

    def ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._states))

    def counts(self, ids: Iterable[int] | None = None) -> dict[State, int]:
        """How many workers are in each state, for a header or a health check."""
        out: dict[State, int] = {}
        for bot_id in self.ids() if ids is None else [int(i) for i in ids]:
            state = self.get(bot_id).state
            out[state] = out.get(state, 0) + 1
        return out


#: Backoff for a supervisor retry: 15s, 30s, 60s … capped at ten minutes, so a
#: revoked token is not hammered and a transient blip recovers quickly.
BACKOFF_BASE = 15.0
BACKOFF_CAP = 600.0


def backoff(attempts: int) -> float:
    """Seconds to wait before attempt number *attempts* + 1."""
    if attempts <= 0:
        return 0.0
    return min(BACKOFF_CAP, BACKOFF_BASE * (2 ** (attempts - 1)))
