"""Agent — shared file storage with per-user quotas.

Deliberately small: a directory plus a JSON index. No database is required for
this phase, and the abstraction is what matters — filestore, leech and saver
all go through it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, *, fallback: str = "file.bin", max_len: int = 80) -> str:
    """Strip paths and unsafe characters from an uploaded name."""
    cleaned = _UNSAFE.sub("_", (name or "").strip()).strip("._")
    cleaned = cleaned[:max_len]
    return cleaned or fallback


@dataclass
class StoredFile:
    id: str
    owner_id: int
    name: str
    size: int
    sha256: str
    created_at: float

    def as_dict(self) -> dict:
        return asdict(self)


class QuotaExceeded(RuntimeError):
    """Raised when a write would exceed the owner's allowance."""


class Storage:
    """Flat file store: ``<root>/files/<id>_<name>`` + JSON index."""

    def __init__(self, root: Path, *, per_user_quota_mb: int = 512) -> None:
        self.root = Path(root)
        self.quota_bytes = max(1, per_user_quota_mb) * 1024 * 1024
        self.files_dir = self.root / "files"
        self._index_path = self.root / "index.json"
        self._index: dict[str, StoredFile] = self._load()

    # -- index -------------------------------------------------------------

    def _load(self) -> dict[str, StoredFile]:
        if not self._index_path.exists():
            return {}
        try:
            raw = json.loads(self._index_path.read_text("utf-8"))
        except (OSError, ValueError):
            logger.warning("Storage index unreadable; starting empty.")
            return {}
        out = {}
        for item in raw.values():
            try:
                out[item["id"]] = StoredFile(**item)
            except (KeyError, TypeError):
                continue
        return out

    def _ensure_dirs(self) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        self._ensure_dirs()
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v.as_dict() for k, v in self._index.items()}), "utf-8")
        tmp.replace(self._index_path)

    # -- usage -------------------------------------------------------------

    def usage(self, owner_id: int) -> int:
        return sum(f.size for f in self._index.values() if f.owner_id == owner_id)

    def check_quota(self, owner_id: int, incoming: int, *, quota_bytes: int | None = None) -> None:
        """Refuse a write that would cross the owner's allowance.

        *quota_bytes* lets the caller pass an allowance that depends on the
        user (the premium tiers do); without it the deployment default applies.
        """
        allowance = self.quota_bytes if quota_bytes is None else int(quota_bytes)
        used = self.usage(owner_id)
        if used + incoming > allowance:
            raise QuotaExceeded(
                f"quota exceeded: {used} + {incoming} > {allowance} bytes"
            )

    # -- writes ------------------------------------------------------------

    def save_bytes(self, owner_id: int, name: str, payload: bytes) -> StoredFile:
        self.check_quota(owner_id, len(payload))
        digest = hashlib.sha256(payload).hexdigest()
        file_id = digest[:16]
        stored = StoredFile(
            id=file_id,
            owner_id=int(owner_id),
            name=safe_filename(name),
            size=len(payload),
            sha256=digest,
            created_at=time.time(),
        )
        self._ensure_dirs()
        path = self.path_for(stored)
        path.write_bytes(payload)
        self._index[file_id] = stored
        self._save()
        return stored

    def save_path(
        self,
        owner_id: int,
        source: Path,
        *,
        name: str | None = None,
        quota_bytes: int | None = None,
    ) -> StoredFile:
        source = Path(source)
        size = source.stat().st_size
        self.check_quota(owner_id, size, quota_bytes=quota_bytes)
        digest = hashlib.sha256()
        with source.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 256), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        stored = StoredFile(
            id=sha[:16],
            owner_id=int(owner_id),
            name=safe_filename(name or source.name),
            size=size,
            sha256=sha,
            created_at=time.time(),
        )
        self._ensure_dirs()
        shutil.copyfile(source, self.path_for(stored))
        self._index[stored.id] = stored
        self._save()
        return stored

    # -- reads -------------------------------------------------------------

    def path_for(self, stored: StoredFile) -> Path:
        return self.files_dir / f"{stored.id}_{stored.name}"

    def get(self, file_id: str) -> StoredFile | None:
        return self._index.get(file_id)

    def owner_of(self, file_id: str) -> int | None:
        stored = self._index.get(file_id)
        return None if stored is None else stored.owner_id

    def list_owned(self, owner_id: int) -> list[StoredFile]:
        return sorted(
            (f for f in self._index.values() if f.owner_id == owner_id),
            key=lambda f: f.created_at,
            reverse=True,
        )

    # -- deletion ----------------------------------------------------------

    def delete(self, file_id: str, *, owner_id: int | None = None) -> bool:
        stored = self._index.get(file_id)
        if stored is None or (owner_id is not None and stored.owner_id != owner_id):
            return False
        with_path = self.path_for(stored)
        with_path.unlink(missing_ok=True)
        self._index.pop(file_id, None)
        self._save()
        return True

    def prune(self, *, retention_days: int, now: float | None = None) -> list[str]:
        """Delete files older than *retention_days*."""
        cutoff = (now or time.time()) - retention_days * 86400
        expired = [f.id for f in self._index.values() if f.created_at < cutoff]
        for file_id in expired:
            self.delete(file_id)
        return expired
