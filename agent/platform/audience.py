"""Who the bot has seen before.

Only ids and timestamps are kept — enough to say "this is a new user" once,
without storing profiles, names or message content.
"""

from __future__ import annotations

import time
from pathlib import Path

from .db import load_document, save_document


class UserIndex:
    """A tiny persistent set of user ids."""

    def __init__(self, root: Path, *, db=None) -> None:
        self._path = Path(root) / "users.json"
        self._db = db
        self._users: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        data = load_document(self._db, "users", self._path, {})
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        save_document(self._db, "users", self._path, self._users)

    def hydrate(self) -> None:
        """Re-read the document; called once PostgreSQL has been loaded."""
        self._users = self._load()

    def seen(self, user_id: int) -> bool:
        return str(int(user_id)) in self._users

    def remember(self, user_id: int) -> bool:
        """Record a user. Returns True when this is the first sighting."""
        key = str(int(user_id))
        if key in self._users:
            return False
        self._users[key] = time.time()
        self._save()
        return True

    def total(self) -> int:
        return len(self._users)
