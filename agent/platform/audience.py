"""Who the bot has seen before.

Only ids and timestamps are kept — enough to say "this is a new user" once,
without storing profiles, names or message content.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class UserIndex:
    """A tiny persistent set of user ids."""

    def __init__(self, root: Path) -> None:
        self._path = Path(root) / "users.json"
        self._users: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._users, indent=2), encoding="utf-8")
        tmp.replace(self._path)

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
