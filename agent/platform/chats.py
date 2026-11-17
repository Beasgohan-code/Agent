"""Agent — per-chat state shared by modules.

Warnings, member notes, trust flags, anti-spam policy and the moderation audit
trail live here. PostgreSQL persists a bot-scoped JSONB document when connected,
with local JSON as the standalone fallback. Group ids partition that document;
warnings use an awaited member-scoped table in PostgreSQL to prevent lost updates.
Other document-backed state is not a safe cross-process slot counter.

Keys are Telegram ids stringified, because JSON object keys must be strings.
"""

from __future__ import annotations

import logging
import time
import uuid
import re
from pathlib import Path

from .db import load_document, save_document
from typing import Any

logger = logging.getLogger(__name__)

#: Caps on the per-chat lists, so one busy group cannot grow the file without end.
MAX_REPORTS = 100
MAX_TRACKS = 200

#: Lower-cased actions an anti-spam hit may take.
SPAM_ACTIONS = ("delete", "warn", "mute", "kick", "ban")

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
    """Document-backed, group-keyed state for the chats this bot moderates."""

    def __init__(
        self,
        root: Path,
        *,
        max_log: int = 200,
        max_warnings: int = 50,
        db=None,
    ) -> None:
        self._path = Path(root) / "chats.json"
        self._max_log = max_log
        self._max_warnings = max_warnings
        #: When a database is connected, this is where the document lives.
        self._db = db
        self._chats: dict[str, dict] = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        data = load_document(self._db, "chats", self._path, {})
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        save_document(self._db, "chats", self._path, self._chats)

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

    def add_warning(self, chat_id: int, user_id: int, *, moderator_id: int, reason: str, expires_at: float | None = None, warning_id: str | None = None) -> int:
        """Record a warning and return how many the member now has active."""
        self._require_local_warnings()
        warning_id=uuid.uuid4().hex if warning_id is None else warning_id
        if not isinstance(warning_id,str) or not re.fullmatch(r'[0-9a-f]{32}',warning_id):
            raise ValueError('Invalid warning identity.')
        if any(row.get('id')==warning_id for row in self._member(chat_id,user_id)['warnings']):
            raise ValueError('Warning identity already exists.')
        if expires_at is None:
            seconds=self.get(chat_id,'warn_expiry_seconds',0)
            if type(seconds) is not int or not (seconds==0 or 60<=seconds<=366*86400):
                raise ValueError('Invalid warning expiry setting.')
            expires_at=time.time()+seconds if seconds else None
        member = self._member(chat_id, user_id)
        member["warnings"].append(
            {
                "id": warning_id,
                "reason": reason[:500],
                "by": int(moderator_id),
                "at": time.time(),
                "active": True,
                "expires_at": expires_at,
            }
        )
        member["warnings"] = member["warnings"][-self._max_warnings :]
        self._save()
        return self.active_warning_count(chat_id, user_id)

    def _require_local_warnings(self):
        if self._db is not None:
            raise RuntimeError("Awaited PostgreSQL warning operation required.")

    async def aadd_warning(self, chat_id, user_id, *, moderator_id, reason, warning_id=None):
        from .warnings import operate
        fields={'moderator_id':moderator_id,'reason':reason}
        if warning_id is not None:
            fields['warning_id']=warning_id
        return await operate(self, chat_id, user_id, 'add_warning',**fields)

    async def aclear_warning_id(self,chat_id,user_id,warning_id,*,actor_id):
        from .warnings import operate
        return await operate(self,chat_id,user_id,'clear_warning_id',warning_id=warning_id,actor_id=actor_id)

    def clear_warning_id(self,chat_id,user_id,*,warning_id,actor_id):
        self._require_local_warnings()
        if (not isinstance(warning_id,str) or not re.fullmatch(r'[0-9a-f]{32}',warning_id)
                or type(actor_id) is not int or not 0<actor_id<2**63):
            raise ValueError('Valid warning identity and personal actor required.')
        self.warnings_of(chat_id,user_id)
        for row in self._member(chat_id,user_id)['warnings']:
            if row.get('id')==warning_id and row.get('active'):
                row.update(active=False,cleared_at=time.time(),cleared_by=actor_id)
                self._save()
                return True
        return False

    async def aclear_warning(self, chat_id, user_id):
        from .warnings import operate
        return await operate(self, chat_id, user_id, 'clear_warning')

    async def aclear_all_warnings(self, chat_id, user_id):
        from .warnings import operate
        return await operate(self, chat_id, user_id, 'clear_all_warnings')

    async def awarnings_of(self, chat_id, user_id):
        from .warnings import operate
        return await operate(self, chat_id, user_id, 'warnings_of')

    async def aactive_warning_count(self, chat_id, user_id):
        return len(await self.awarnings_of(chat_id, user_id))

    def active_warning_count(self, chat_id: int, user_id: int) -> int:
        return len(self.warnings_of(chat_id, user_id))

    def warnings_of(self, chat_id: int, user_id: int) -> list[dict]:
        self._require_local_warnings()
        member = self._chat(chat_id)["members"].get(str(int(user_id)), {})
        changed=False
        now=time.time()
        for warning in member.get('warnings',[]):
            expiry=warning.get('expires_at')
            if expiry is not None and (type(expiry) not in (int,float) or not 0<expiry<float('inf')):
                raise ValueError('Invalid warning expiry record.')
            if warning.get('active') and expiry is not None and expiry<=now:
                warning.update(active=False,expired_at=now)
                changed=True
        if changed:
            self._save()
        return [w for w in member.get("warnings", []) if w.get("active")]

    def clear_warning(self, chat_id: int, user_id: int) -> bool:
        """Clear the most recent active warning. False when there was none."""
        self._require_local_warnings()
        member = self._member(chat_id, user_id)
        self.warnings_of(chat_id,user_id)
        for warning in reversed(member["warnings"]):
            if warning.get("active"):
                warning["active"] = False
                warning["cleared_at"] = time.time()
                self._save()
                return True
        return False

    def clear_all_warnings(self, chat_id: int, user_id: int) -> int:
        """Clear every active warning; return how many were cleared."""
        self._require_local_warnings()
        member = self._member(chat_id, user_id)
        self.warnings_of(chat_id,user_id)
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
        if self._db is not None:
            from .group_trust import TrustError
            raise TrustError("Awaited PostgreSQL trust update required.")
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
        if self._db is not None:
            from .antispam import PolicyError
            raise PolicyError("Awaited PostgreSQL protection update required.")
        self._chat(chat_id)["settings"]["antispam"] = policy
        self._save()
        return self.antispam(chat_id)

    def settings(self, chat_id: int) -> dict:
        return self._chat(chat_id)["settings"]

    # -- message filters ---------------------------------------------------

    def filters(self, chat_id: int) -> dict[str, str]:
        return dict(self._chat(chat_id)["settings"].get("filters") or {})

    def set_filter(self, chat_id: int, name: str, reply: str, *, by: int) -> None:
        if self._db is not None:
            from .group_filters import FilterError
            raise FilterError("Awaited PostgreSQL filter update required.")
        settings = self._chat(chat_id)["settings"]
        filters = settings.setdefault("filters", {})
        filters[name.strip().lower()[:64]] = reply[:2000]
        settings.setdefault("filter_authors", {})[name.strip().lower()[:64]] = int(by)
        self._save()

    def remove_filter(self, chat_id: int, name: str) -> bool:
        if self._db is not None:
            from .group_filters import FilterError
            raise FilterError("Awaited PostgreSQL filter update required.")
        settings = self._chat(chat_id)["settings"]
        filters = settings.setdefault("filters", {})
        removed = filters.pop(name.strip().lower()[:64], None) is not None
        if removed:
            settings.get('filter_authors', {}).pop(name.strip().lower()[:64], None)
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

    # -- reports and appeals -----------------------------------------------

    def add_report(
        self,
        chat_id: int,
        *,
        reporter_id: int,
        reason: str = "",
        target_id: int | None = None,
        message_id: int | None = None,
        kind: str = "report",
    ) -> int:
        """Record a report/appeal and return its per-chat number."""
        settings = self._chat(chat_id)["settings"]
        sequence = int(settings.get("report_seq", 0)) + 1
        settings["report_seq"] = sequence
        entries = settings.setdefault("reports", [])
        entries.append(
            {
                "id": sequence,
                "kind": kind,
                "reporter": int(reporter_id),
                "target": None if target_id is None else int(target_id),
                "message_id": None if message_id is None else int(message_id),
                "reason": reason[:500],
                "state": "open",
                "at": time.time(),
            }
        )
        del entries[:-MAX_REPORTS]
        self._save()
        return sequence

    def reports(self, chat_id: int, *, state: str = "open", limit: int = 20) -> list[dict]:
        entries = self._chat(chat_id)["settings"].get("reports") or []
        matching = [entry for entry in entries if entry.get("state") == state]
        return matching[-limit:] if limit > 0 else []

    def close_report(self, chat_id: int, report_id: int, *, by: int | None = None) -> bool:
        entries = self._chat(chat_id)["settings"].get("reports") or []
        for entry in entries:
            if entry.get("id") == int(report_id) and entry.get("state") == "open":
                entry["state"] = "closed"
                entry["closed_by"] = None if by is None else int(by)
                entry["closed_at"] = time.time()
                self._save()
                return True
        return False

    # -- audio catalogue ----------------------------------------------------

    def music(self, chat_id: int) -> list[dict]:
        return list(self._chat(chat_id)["settings"].get("music") or [])

    def add_music(self, chat_id: int, entry: dict) -> int:
        """Append one track; returns its 1-based position in the catalogue."""
        tracks = self._chat(chat_id)["settings"].setdefault("music", [])
        tracks.append({**entry, "added_at": time.time()})
        del tracks[:-MAX_TRACKS]
        self._save()
        return len(tracks)

    def remove_music(self, chat_id: int, position: int) -> dict | None:
        """Remove the 1-based *position*; returns the removed entry."""
        tracks = self._chat(chat_id)["settings"].setdefault("music", [])
        if not 1 <= int(position) <= len(tracks):
            return None
        entry = tracks.pop(int(position) - 1)
        self._save()
        return entry

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

    def known_group_page(self, page: int, *, size: int = 10):
        """Scoped cached chat index, not Telegram-wide discovery or admin proof."""
        if type(page) is not int or page < 1 or not 1 <= size <= 10:
            raise ValueError('Invalid chat page')
        ids = sorted({int(key) for key in self._chats
                      if isinstance(key, str) and key.startswith('-')
                      and key[1:].isascii() and key[1:].isdigit()
                      and len(key) <= 20 and -(2**63) < int(key) < 0}, reverse=True)
        return ids[(page - 1) * size:page * size], len(ids)

    def history(self, chat_id: int, *, limit: int = 10) -> list[dict]:
        entries = self._chat(chat_id)["log"]
        return list(reversed(entries))[: max(0, limit)]
