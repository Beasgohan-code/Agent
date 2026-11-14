"""Agent — shared file storage with per-user quotas.

Two things live here and they have different lifetimes:

* the **index** — which file belongs to whom, how big, which hash. With a
  database it is a scoped PostgreSQL document, so it survives a redeploy;
* the **bytes** — on disk by default, or in a Telegram storage channel once an
  archive uploader is attached. Delivery prefers the archived ``file_id``
  (:func:`agent.utils.attachments.deliver_stored`), so a wiped container is a
  slow first request, not a lost file.

Quota accounting, hashing and filename hygiene are deliberately the same in both
modes: the only thing that changes is where the bytes sleep.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .db import load_document, save_document

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
    #: Telegram ``file_id`` once the bytes are archived in the storage channel.
    #: With one, delivery sends cached media and never touches this disk.
    telegram_file_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class QuotaExceeded(RuntimeError):
    """Raised when a write would exceed the owner's allowance."""


class Storage:
    """Flat file store: ``<root>/files/<id>_<name>`` plus an index.

    The index is the thing that must survive a redeploy: with ``db`` it is a
    document in PostgreSQL (scoped per bot, like every other store), so a
    container that is replaced still knows every file it ever stored.

    The *bytes* have two homes. By default they sit on the host's disk under
    ``DATA_DIR`` — correct for one long-lived VPS, wrong for a container whose
    filesystem is wiped on every deploy. Attaching an ``archive`` uploader (see
    :meth:`attach_archive`) sends each stored file to a private Telegram storage
    channel and keeps its ``file_id``; delivery then uses cached media, which
    costs nothing to fetch and cannot be lost with a disk.
    """

    def __init__(
        self,
        root: Path,
        *,
        per_user_quota_mb: int = 512,
        db=None,
        archive=None,
    ) -> None:
        self.root = Path(root)
        self.quota_bytes = max(1, per_user_quota_mb) * 1024 * 1024
        self.files_dir = self.root / "files"
        self._index_path = self.root / "index.json"
        #: PostgreSQL document store; None keeps the JSON index.
        self._db = db
        #: ``async (path, name) -> telegram file_id``, set once a client exists.
        self._archive = archive
        self._index: dict[str, StoredFile] = self._load()

    # -- index -------------------------------------------------------------

    def _load(self) -> dict[str, StoredFile]:
        raw = load_document(self._db, "files", self._index_path, {})
        if not isinstance(raw, dict) or not raw:
            return {}
        out = {}
        for item in raw.values():
            try:
                out[item["id"]] = StoredFile(**item)
            except (KeyError, TypeError):
                # A record from an older shape is dropped, not fatal: the bytes
                # are still on disk and the user can re-save the file.
                logger.warning("skipping a malformed storage record")
                continue
        return out

    def _ensure_dirs(self) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        save_document(
            self._db,
            "files",
            self._index_path,
            {key: value.as_dict() for key, value in self._index.items()},
        )

    def hydrate(self) -> None:
        """Re-read the index after the database has been loaded."""
        self._index = self._load()

    # -- archiving ---------------------------------------------------------
    def attach_archive(self, uploader) -> None:
        """Give the store a way to put bytes in Telegram (or anywhere durable)."""
        self._archive = uploader

    @property
    def archiving(self) -> bool:
        return self._archive is not None

    async def archive(self, stored: StoredFile) -> str:
        """Send one file to the archive and remember its ``file_id``."""
        if self._archive is None or stored.telegram_file_id:
            return stored.telegram_file_id
        path = self.path_for(stored)
        if not path.exists():
            return ""
        try:
            file_id = await self._archive(path, stored.name)
        except Exception:  # noqa: BLE001 - a failed archive must not lose the file
            logger.warning("could not archive %s", stored.name, exc_info=True)
            return ""
        if self._index.get(stored.id) is not stored:
            # An archive upload finishing after deletion must not resurrect it.
            return ""
        if file_id:
            stored.telegram_file_id = str(file_id)
            self._index[stored.id] = stored
            self._save()
            logger.info("archived %s to the storage channel", stored.name)
        return stored.telegram_file_id

    def schedule_archive(self, stored: StoredFile) -> None:
        """Archive in the background; a store used without a loop stays quiet."""
        if self._archive is None or stored.telegram_file_id:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # A synchronous caller (a script, a test) has no loop to schedule on;
            # the file stays on disk and the next hydrated store still lists it.
            logger.debug("no event loop; %s stays on disk", stored.name)
            return
        loop.create_task(self.archive(stored), name=f"archive-{stored.id}")

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
        file_id = self._new_id()
        stored = StoredFile(
            id=file_id,
            owner_id=int(owner_id),
            name=safe_filename(name),
            size=len(payload),
            sha256=digest,
            created_at=time.time(),
        )
        return self._store(stored, lambda path: path.write_bytes(payload))

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
            id=self._new_id(),
            owner_id=int(owner_id),
            name=safe_filename(name or source.name),
            size=size,
            sha256=sha,
            created_at=time.time(),
        )
        return self._store(stored, lambda path: shutil.copyfile(source, path))

    def _new_id(self) -> str:
        # IDs are handles, not content hashes. Identical uploads must never
        # transfer ownership or replace metadata referenced by existing links.
        for _ in range(10):
            file_id = secrets.token_hex(16)
            if file_id not in self._index:
                return file_id
        raise RuntimeError("Could not allocate a unique storage handle")

    def _store(self, stored: StoredFile, write) -> StoredFile:
        self._ensure_dirs()
        path = self.path_for(stored)
        try:
            write(path)
            self._index[stored.id] = stored
            self._save()
        except BaseException:
            self._index.pop(stored.id, None)
            path.unlink(missing_ok=True)
            raise
        self.schedule_archive(stored)
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
        self._index.pop(file_id, None)
        try:
            self._save()
        except BaseException:
            self._index[file_id] = stored
            raise
        with_path.unlink(missing_ok=True)
        return True

    def prune(self, *, retention_days: int, now: float | None = None) -> list[str]:
        """Delete files older than *retention_days*."""
        cutoff = (now or time.time()) - retention_days * 86400
        expired = [f.id for f in self._index.values() if f.created_at < cutoff]
        for file_id in expired:
            self.delete(file_id)
        return expired
