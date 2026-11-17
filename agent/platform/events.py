"""A small, bounded event log.

Modules emit what they did; the log keeps the most recent entries in memory and
writes each one to the normal logger so it also lands in the platform's log
stream. Nothing is persisted — this is an operational view, not an audit trail
(the per-chat moderation log is the audit trail).
"""

from __future__ import annotations

import logging
import copy
import time
from .log_safety import safe_fields, safe_value
from collections import deque
from typing import Any

logger = logging.getLogger("agent.events")


class EventLog:
    """Ring buffer of recent events, newest last."""

    def __init__(self, maxlen: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max(10, maxlen))
        self._listeners: list[Any] = []

    def emit(self, kind: str, **fields: Any) -> dict[str, Any]:
        kind = str(safe_value(kind)).replace("\n"," ")
        fields = safe_fields(fields)
        event = {**fields, "kind": kind, "at": time.time()}
        self._events.append(event)
        detail = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info("%s %s", kind, detail)
        for listener in list(self._listeners):
            try:
                listener(kind, copy.deepcopy(fields))
            except Exception as error:  # a listener must not break/leak through emitter
                logger.warning("#Errors Event listener failed error_type=%s",type(error).__name__)
        return copy.deepcopy(event)

    def subscribe(self, listener: Any) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Any) -> None:
        self._listeners = [item for item in self._listeners if item is not listener]

    def recent(self, limit: int = 10, *, kind: str | None = None) -> list[dict[str, Any]]:
        if limit<=0:
            return []
        items = [copy.deepcopy(e) for e in self._events if kind is None or e["kind"] == kind]
        return items[-max(0, limit) :][::-1]

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self._events)
        return sum(1 for e in self._events if e["kind"] == kind)

    def clear(self) -> None:
        self._events.clear()

    def listeners(self) -> int:
        return len(self._listeners)
