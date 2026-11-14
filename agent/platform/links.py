"""Agent — signed share links (linkshare / filestore).

Tokens are HMAC-signed and carry their own expiry, so validation needs no
database lookups. Revocation is the one thing that needs state, kept in a
small JSON file.

Nothing here exposes storage identifiers to the user: the token *is* the
handle, and it is opaque.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class LinkError(RuntimeError):
    """Raised when a token is malformed, expired or revoked."""


@dataclass
class LinkRecord:
    token: str
    file_id: str
    owner_id: int
    created_at: float
    expires_at: float
    revoked: bool = False
    uses: int = 0

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class LinkStore:
    """Creates, validates and revokes signed file links."""

    def __init__(self, root: Path, secret: str, *, default_ttl_hours: int = 24) -> None:
        self.root = Path(root)
        self._secret = (secret or "").encode() or secrets.token_bytes(32)
        self.default_ttl = max(1, default_ttl_hours) * 3600
        self._path = self.root / "links.json"
        self._links: dict[str, LinkRecord] = self._load()

    def _load(self) -> dict[str, LinkRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text("utf-8"))
            return {k: LinkRecord(**v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            logger.warning("Link index unreadable; starting empty.")
            return {}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in self._links.items()}), "utf-8")
        tmp.replace(self._path)

    # -- signing -----------------------------------------------------------

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()[:16])

    def create(self, file_id: str, owner_id: int, *, ttl_hours: int | None = None) -> LinkRecord:
        ttl = (ttl_hours or self.default_ttl // 3600) * 3600
        payload = f"{file_id}.{int(owner_id)}.{int(time.time() + ttl)}"
        token = f"{payload}.{self._sign(payload)}"
        record = LinkRecord(
            token=token,
            file_id=file_id,
            owner_id=int(owner_id),
            created_at=time.time(),
            expires_at=time.time() + ttl,
        )
        self._links[token] = record
        self._save()
        return record

    def resolve(self, token: str) -> LinkRecord:
        """Return the record for *token*, or raise :class:`LinkError`."""
        record = self._links.get(token)
        if record is not None:
            if record.revoked:
                raise LinkError("link revoked")
            if record.expired:
                raise LinkError("link expired")
            return record

        # Not in the index: still verify the signature so a forged token of the
        # right shape cannot be mistaken for an unknown-but-valid one.
        parts = (token or "").split(".")
        if len(parts) != 4:
            raise LinkError("malformed link")
        payload, signature = ".".join(parts[:3]), parts[3]
        if not hmac.compare_digest(self._sign(payload), signature):
            raise LinkError("bad signature")
        file_id, owner, expiry = parts[0], parts[1], parts[2]
        if not expiry.isdigit() or int(expiry) <= time.time():
            raise LinkError("link expired")
        return LinkRecord(
            token=token,
            file_id=file_id,
            owner_id=int(owner) if owner.lstrip("-").isdigit() else 0,
            created_at=0.0,
            expires_at=float(expiry),
        )

    def consume(self, token: str) -> LinkRecord:
        """Like :meth:`resolve`, incrementing the use counter."""
        record = self.resolve(token)
        stored = self._links.get(token)
        if stored is not None:
            stored.uses += 1
            self._save()
        return record

    def revoke(self, token: str, *, owner_id: int | None = None) -> bool:
        record = self._links.get(token)
        if record is None or record.revoked:
            return False
        if owner_id is not None and record.owner_id != owner_id:
            return False
        record.revoked = True
        self._save()
        return True

    def owned(self, owner_id: int) -> list[LinkRecord]:
        return sorted(
            (r for r in self._links.values() if r.owner_id == owner_id),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def verify_signature(self, token: str) -> bool:
        parts = (token or "").split(".")
        if len(parts) != 4:
            return False
        payload, signature = ".".join(parts[:3]), parts[3]
        try:
            _unb64(signature)
        except (binascii.Error, ValueError):
            return False
        return hmac.compare_digest(self._sign(payload), signature)
