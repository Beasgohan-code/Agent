"""Per-chat playback queue — pure state, no Telegram and no audio.

Keeping the queue separate from the engine is what makes it testable: the
ordering rules (what ``/skip`` plays next, what happens when the last track ends,
what a duplicate request means) are decided here and can be asserted without a
voice chat anywhere in sight.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Track:
    """One queued request."""

    title: str
    source: str
    requested_by: int | None = None

    def describe(self) -> str:
        who = f" (by {self.requested_by})" if self.requested_by else ""
        return f"{self.title}{who}"


@dataclass
class ChatQueue:
    """FIFO queue with a current track, per chat."""

    current: Track | None = None
    waiting: list[Track] = field(default_factory=list)
    loop: bool = False

    def add(self, track: Track) -> int:
        """Queue *track*; returns its 1-based position in the waiting list."""
        self.waiting.append(track)
        return len(self.waiting)

    def advance(self) -> Track | None:
        """Move to the next track; returns it, or ``None`` when the queue ends."""
        if self.current is not None and self.loop:
            return self.current
        self.current = self.waiting.pop(0) if self.waiting else None
        return self.current

    def stop(self) -> None:
        self.current = None
        self.waiting.clear()

    def remove(self, position: int) -> Track | None:
        """Remove the 1-based *position* from the waiting list."""
        if not 1 <= position <= len(self.waiting):
            return None
        return self.waiting.pop(position - 1)

    @property
    def size(self) -> int:
        return len(self.waiting) + (1 if self.current else 0)


class QueueBook:
    """Every chat's queue, in memory only."""

    def __init__(self) -> None:
        self._queues: dict[int, ChatQueue] = {}

    def for_chat(self, chat_id: int) -> ChatQueue:
        return self._queues.setdefault(int(chat_id), ChatQueue())

    def drop(self, chat_id: int) -> None:
        self._queues.pop(int(chat_id), None)

    def chats(self) -> list[int]:
        return list(self._queues)
