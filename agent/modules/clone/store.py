"""Where clones are recorded, and what a record may say.

A clone is one bot token plus the person who added it. The token is the one
secret this store holds, so the file is written ``0600`` and the panel never
shows more than its first digits; :meth:`Clone.masked` is the only form that
reaches a screen.

Records are keyed by the bot id inside the token, not by owner: Telegram already
decides that a token identifies one bot, and two records for one bot would be
two clients answering the same updates.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: ``<bot_id>:<secret>`` — the shape @BotFather hands out.
TOKEN_RE = re.compile(r"^(?P<bot_id>\d{6,12}):(?P<secret>[A-Za-z0-9_-]{25,})$")


def parse_token(raw: str) -> tuple[bool, str, int]:
    """``(ok, reason, bot_id)`` for a pasted token, checked without the network.

    Shape is not identity: a well-formed token can still be revoked, and only
    ``getMe`` knows that. This check exists so a typo never reaches Telegram.
    """
    text = (raw or "").strip()
    if not text:
        return False, "Send the token from @BotFather after the command.", 0
    match = TOKEN_RE.match(text)
    if match is None:
        return (
            False,
            "That is not a bot token: it looks like <code>123456789:AA…</code>.",
            0,
        )
    return True, "", int(match.group("bot_id"))


@dataclass
class Clone:
    """One cloned bot."""

    bot_id: int
    owner_id: int
    token: str
    username: str = ""
    name: str = ""
    created_at: float = field(default_factory=time.time)
    #: Set when an owner parks a clone; it stays in the list but is not started.
    disabled: bool = False

    @property
    def handle(self) -> str:
        return f"@{self.username}" if self.username else f"bot {self.bot_id}"

    @property
    def masked(self) -> str:
        """Enough of the token to recognise it, never enough to use it."""
        return f"{self.bot_id}:{self.token.split(':', 1)[-1][:4]}…"

    def as_json(self) -> dict:
        return asdict(self)


class CloneStore:
    """A JSON list of clones, rewritten atomically on every change."""

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / "clones.json"
        self._items: dict[int, Clone] = self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> dict[int, Clone]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("clones.json is unreadable; starting with no clones")
            return {}
        items: dict[int, Clone] = {}
        for entry in raw if isinstance(raw, list) else []:
            try:
                clone = Clone(
                    bot_id=int(entry["bot_id"]),
                    owner_id=int(entry["owner_id"]),
                    token=str(entry["token"]),
                    username=str(entry.get("username") or ""),
                    name=str(entry.get("name") or ""),
                    created_at=float(entry.get("created_at") or 0.0),
                    disabled=bool(entry.get("disabled")),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("skipping a malformed clone record: %r", entry)
                continue
            items[clone.bot_id] = clone
        return items

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [clone.as_json() for clone in self._items.values()], indent=2, sort_keys=True
        )
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:  # pragma: no cover - a filesystem without modes
            logger.debug("could not restrict clones.json permissions", exc_info=True)
        temp.replace(self.path)

    # -- reads ------------------------------------------------------------
    def get(self, bot_id: int) -> Clone | None:
        return self._items.get(int(bot_id))

    def all(self) -> tuple[Clone, ...]:
        return tuple(
            sorted(self._items.values(), key=lambda clone: clone.created_at, reverse=True)
        )

    def by_owner(self, owner_id: int) -> tuple[Clone, ...]:
        return tuple(c for c in self.all() if c.owner_id == int(owner_id))

    def count(self) -> int:
        return len(self._items)

    # -- writes -----------------------------------------------------------
    def add(self, clone: Clone) -> Clone:
        self._items[clone.bot_id] = clone
        self._save()
        return clone

    def update(self, bot_id: int, **fields) -> Clone | None:
        clone = self._items.get(int(bot_id))
        if clone is None:
            return None
        for key, value in fields.items():
            if hasattr(clone, key):
                setattr(clone, key, value)
        self._save()
        return clone

    def remove(self, bot_id: int) -> bool:
        if self._items.pop(int(bot_id), None) is None:
            return False
        self._save()
        return True
