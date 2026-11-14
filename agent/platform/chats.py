"""Agent — per-chat state shared by modules.

Warnings, member notes, trust flags, anti-spam policy and the moderation audit
trail live here. They are plain JSON on disk, not a database: the surface this
bot actually needs is small enough that a schema and a migration tool would be
overhead, and the file is easy to inspect and to back up.

Keys are Telegram ids stringified, because JSON object keys must be strings.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Lower-cased actions an anti-spam hit may take.
SPAM_ACTIONS = ("delete", "warn", "mute", "kick", "ban")

#: Anti-spam defaults, matching the policy Meikoagent documents.
DEFAULT_ANTISPAM: dict[str, Any] = {
    "flood_enabled": True,
    "flood_messages": 7,
    "flood_window_seconds": 8,
    "duplicate_enabled": True,
    "duplicate_threshold": 3,
    "links_enabled": True,
    "invites_enabled": True,
    "keywords_enabled": False,
    "blocked_keywords": [],
    "action": "warn",
    "mute_seconds": 300,
}


class ChatStore:
    """JSON-backed state for every chat the bot moderates."""

    def __init__(self, root: Path, *, max_log: int = 200, max_warnings: int = 50) -> None:
        self._path = Path(root) / "chats.json"
        self._max_log = max_log
        self._max_warnings = max_warnings
        self._chats: dict[str, dict] = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("chats.json unreadable; starting from an empty store")
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._chats, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def _chat(self, chat_id: int) -> dict:
        return self._chats.setdefault(
            str(int(chat_id)), {"members": {}, "settings": {}, "log": []}
        )

    def _member(self, chat_id: int, user_id: int) -> dict:
        members = self._chat(chat_id)["members"]
        return members.setdefault(
            str(int(user_id)), {"warnings": [], "note": "", "trusted": False}
        )

    # -- warnings ----------------------------------------------------------

    def add_warning(self, chat_id: int, user_id: int, *, moderator_id: int, reason: str) -> int:
        """Record a warning and return how many the member now has active."""
        member = self._member(chat_id, user_id)
        member["warnings"].append(
            {
                "reason": reason[:500],
                "by": int(moderator_id),
                "at": time.time(),
                "active": True,
            }
        )
        member["warnings"] = member["warnings"][-self._max_warnings :]
        self._save()
        return self.active_warning_count(chat_id, user_id)

    def active_warning_count(self, chat_id: int, user_id: int) -> int:
        return len(self.warnings_of(chat_id, user_id))

    def warnings_of(self, chat_id: int, user_id: int) -> list[dict]:
        member = self._chat(chat_id)["members"].get(str(int(user_id)), {})
        return [w for w in member.get("warnings", []) if w.get("active")]

    def clear_warning(self, chat_id: int, user_id: int) -> bool:
        """Clear the most recent active warning. False when there was none."""
        member = self._member(chat_id, user_id)
        for warning in reversed(member["warnings"]):
            if warning.get("active"):
                warning["active"] = False
                warning["cleared_at"] = time.time()
                self._save()
                return True
        return False

    def clear_all_warnings(self, chat_id: int, user_id: int) -> int:
        """Clear every active warning; return how many were cleared."""
        member = self._member(chat_id, user_id)
        cleared = 0
        now = time.time()
        for warning in member["warnings"]:
            if warning.get("active"):
                warning["active"] = False
                warning["cleared_at"] = now
                cleared += 1
        if cleared:
            self._save()
        return cleared

    def trusted_count(self, chat_id: int) -> int:
        members = self._chat(chat_id)["members"]
        return sum(1 for member in members.values() if member.get("trusted"))

    # -- member metadata ---------------------------------------------------

    def set_note(self, chat_id: int, user_id: int, note: str) -> None:
        self._member(chat_id, user_id)["note"] = note[:2000]
        self._save()

    def note_of(self, chat_id: int, user_id: int) -> str:
        member = self._chat(chat_id)["members"].get(str(int(user_id)), {})
        return member.get("note", "")

    def toggle_trust(self, chat_id: int, user_id: int) -> bool:
        """Flip the trusted flag and return its new value."""
        member = self._member(chat_id, user_id)
        member["trusted"] = not member.get("trusted", False)
        self._save()
        return bool(member["trusted"])

    def is_trusted(self, chat_id: int, user_id: int) -> bool:
        member = self._chat(chat_id)["members"].get(str(int(user_id)), {})
        return bool(member.get("trusted", False))

    # -- settings ----------------------------------------------------------

    def antispam(self, chat_id: int) -> dict:
        stored = self._chat(chat_id)["settings"].get("antispam") or {}
        return {**DEFAULT_ANTISPAM, **stored}

    def save_antispam(self, chat_id: int, policy: dict) -> dict:
        self._chat(chat_id)["settings"]["antispam"] = policy
        self._save()
        return self.antispam(chat_id)

    def settings(self, chat_id: int) -> dict:
        return self._chat(chat_id)["settings"]

    # -- message filters ---------------------------------------------------

    def filters(self, chat_id: int) -> dict[str, str]:
        return dict(self._chat(chat_id)["settings"].get("filters") or {})

    def set_filter(self, chat_id: int, name: str, reply: str, *, by: int) -> None:
        settings = self._chat(chat_id)["settings"]
        filters = settings.setdefault("filters", {})
        filters[name.strip().lower()[:64]] = reply[:2000]
        settings.setdefault("filter_authors", {})[name.strip().lower()[:64]] = int(by)
        self._save()

    def remove_filter(self, chat_id: int, name: str) -> bool:
        settings = self._chat(chat_id)["settings"]
        filters = settings.setdefault("filters", {})
        removed = filters.pop(name.strip().lower()[:64], None) is not None
        if removed:
            self._save()
        return removed

    def match_filter(self, chat_id: int, text: str) -> str | None:
        """The reply of the first filter whose name appears in *text*."""
        body = (text or "").strip().lower()
        if not body:
            return None
        for name, reply in self.filters(chat_id).items():
            if name and name in body:
                return reply
        return None

    # -- greetings ---------------------------------------------------------

    def greeting(self, chat_id: int, kind: str) -> dict:
        stored = (self._chat(chat_id)["settings"].get("greetings") or {}).get(kind) or {}
        return {"text": stored.get("text", ""), "enabled": stored.get("enabled", False)}

    def set_greeting(self, chat_id: int, kind: str, text: str) -> dict:
        greetings = self._chat(chat_id)["settings"].setdefault("greetings", {})
        greetings[kind] = {"text": text[:1500], "enabled": True}
        self._save()
        return self.greeting(chat_id, kind)

    def toggle_greeting(self, chat_id: int, kind: str, enabled: bool) -> dict:
        greetings = self._chat(chat_id)["settings"].setdefault("greetings", {})
        current = greetings.setdefault(kind, {"text": "", "enabled": False})
        current["enabled"] = bool(enabled)
        self._save()
        return self.greeting(chat_id, kind)

    # -- generic per-chat settings -----------------------------------------

    def get(self, chat_id: int, key: str, default=None):
        return self._chat(chat_id)["settings"].get(key, default)

    def put(self, chat_id: int, key: str, value) -> None:
        self._chat(chat_id)["settings"][key] = value
        self._save()

    # -- audit trail -------------------------------------------------------

    def log(
        self,
        chat_id: int,
        action: str,
        *,
        actor_id: int | None,
        target_id: int | None = None,
        reason: str = "",
    ) -> None:
        entries = self._chat(chat_id)["log"]
        entries.append(
            {
                "action": action,
                "actor": None if actor_id is None else int(actor_id),
                "target": None if target_id is None else int(target_id),
                "reason": reason[:500],
                "at": time.time(),
            }
        )
        del entries[: max(0, len(entries) - self._max_log)]
        self._save()

    def history(self, chat_id: int, *, limit: int = 10) -> list[dict]:
        entries = self._chat(chat_id)["log"]
        return list(reversed(entries))[: max(0, limit)]
