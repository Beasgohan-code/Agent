"""Agent — the owner log channel.

Every notable event is posted to one channel, tagged with a searchable hashtag
(``#NewUser``, ``#NewGroup``, ``#Restart`` …). When no channel is configured the
events go to the owner's DM instead, so an owner who never set one still sees
them. A failed post is logged and dropped; it never breaks a command.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Event kind → hashtag. Unknown kinds get a CamelCase tag of their own.
TAGS = {
    "start": "BotStarted",
    "stop": "BotStopped",
    "new_user": "NewUser",
    "returning_user": "Start",
    "new_group": "NewGroup",
    "restart": "Restart",
    "plugin": "Plugin",
    "watchdog": "Watchdog",
    "error": "Error",
    "instance": "Instance",
}


def tag_for(kind: str) -> str:
    if kind in TAGS:
        return TAGS[kind]
    return "".join(part.capitalize() for part in kind.replace("-", "_").split("_")) or "Event"


def format_event(kind: str, fields: dict[str, Any], *, when: float | None = None) -> str:
    """Render one event as HTML for the log channel."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(when or time.time()))
    lines = [f"<b>#{tag_for(kind)}</b>", f"<i>{stamp}</i>"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        lines.append(f"{html.escape(str(key))}: <code>{html.escape(str(value))}</code>")
    return "\n".join(lines)


class LogBook:
    """Posts events to the log channel, or to the owner when there is none."""

    def __init__(
        self,
        root: Path,
        *,
        channel_id: int | None = None,
        owner_id: int | None = None,
    ) -> None:
        self._path = Path(root) / "logbook.json"
        self._channel_id = channel_id
        self.owner_id = owner_id
        self.client = None
        stored = self._load()
        if stored.get("channel_id") is not None:
            self._channel_id = int(stored["channel_id"])

    # -- configuration -----------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"channel_id": self._channel_id}), encoding="utf-8"
        )

    @property
    def channel_id(self) -> int | None:
        return self._channel_id

    def destination(self) -> int | None:
        """Where events go: the channel, else the owner, else nowhere yet."""
        return self._channel_id if self._channel_id is not None else self.owner_id

    def set_channel(self, channel_id: int | None) -> None:
        self._channel_id = None if channel_id is None else int(channel_id)
        self._save()

    # -- delivery ----------------------------------------------------------

    async def post(self, kind: str, **fields: Any) -> bool:
        """Send one event. False when there is nowhere (or no client) to send it."""
        target = self.destination()
        if self.client is None or target is None:
            logger.info("#%s %s (no log destination)", tag_for(kind), fields)
            return False
        text = format_event(kind, fields)
        try:
            await self.client.send_message(target, text, disable_web_page_preview=True)
            return True
        except Exception:  # noqa: BLE001 - logging must never break the bot
            logger.exception("Could not post #%s to the log channel", tag_for(kind))
            return False

    def publish(self, kind: str, fields: dict[str, Any]) -> None:
        """Fire-and-forget from a synchronous context (the event log)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop outside a running bot
            return
        task = loop.create_task(self.post(kind, **fields))
        # Keep a reference so the task is not garbage-collected mid-flight.
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)


_PENDING: set[asyncio.Task] = set()


def subscribe(event_log, logbook: LogBook) -> Callable[[], None]:
    """Bridge an :class:`EventLog` to the channel. Returns an unsubscribe."""
    def listener(kind: str, fields: dict[str, Any]) -> None:
        logbook.publish(kind, fields)

    event_log.subscribe(listener)
    return lambda: event_log.unsubscribe(listener)
