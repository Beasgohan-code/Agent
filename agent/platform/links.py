"""Agent — signed share links (linkshare / filestore).

Tokens are HMAC-signed opaque handles. Expiry, revocation and use caps require
an existing persisted record; a signature alone never reconstructs a grant.
New handles are compact URL-safe random values suitable for Telegram deep links
and callback buttons. Existing indexed legacy handles remain supported.

Nothing here exposes storage identifiers to the user: the token *is* the
handle, and it is opaque.

A token is also the thing a link button carries: ``t.me/<bot>?start=link_<token>``
hands it back to :func:`agent.handlers.commands.CommandHandlers.start`, which
routes it to the module that owns the ``link`` prefix. Expiry, revocation and
the use cap are all checked there, in that order, before a file is sent.
"""

from __future__ import annotations

import base64
import copy
import json
import binascii
import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .db import load_document, save_document

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
    #: How many times the link may be redeemed; ``0`` means unlimited.
    max_uses: int = 0
    redemption_requests: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def exhausted(self) -> bool:
        return bool(self.max_uses) and self.uses >= self.max_uses

    @property
    def remaining(self) -> int | None:
        """Uses left, or ``None`` for a link with no cap."""
        return None if not self.max_uses else max(0, self.max_uses - self.uses)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class LinkStore:
    """Creates, validates and revokes signed file links."""

    def __init__(
        self, root: Path, secret: str, *, default_ttl_hours: int = 24, db=None
    ) -> None:
        self.root = Path(root)
        self._secret = (secret or "").encode() or secrets.token_bytes(32)
        self.default_ttl = max(1, default_ttl_hours) * 3600
        self._path = self.root / "links.json"
        self._db = db
        self._links: dict[str, LinkRecord] = self._load()

    def _load(self) -> dict[str, LinkRecord]:
        raw = load_document(self._db, "links", self._path, {})
        if not isinstance(raw, dict):
            return {}
        records: dict[str, LinkRecord] = {}
        for key, value in raw.items():
            try:
                records[key] = LinkRecord(**value)
            except TypeError:
                logger.warning("skipping a malformed link record")
        return records

    def _save(self) -> None:
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        save_document(
            self._db, "links", self._path, {k: asdict(v) for k, v in self._links.items()}
        )

    async def _atomic(self, operation, *args, **kwargs):
        """Serialize scoped document reads/mutations in an awaited transaction.

        This preserves existing tokens and JSONB records without a destructive
        migration. It deliberately bypasses the legacy background writer.
        All participating processes must use this awaited API.
        """
        if self._db is None:
            return getattr(self, operation)(*args, **kwargs)
        db = self._db
        if not db.connected or getattr(db, "_pool", None) is None:
            raise LinkError("Database link state is unavailable")
        if "links" in getattr(db, "_pending", {}):
            raise LinkError("Legacy link write pending; retry after it is flushed")
        try:
            async with db._pool.acquire(timeout=5) as connection:
                async with connection.transaction():
                    key = db.name_for("links")
                    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", key, timeout=5)
                    raw = await connection.fetchval("SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE", key, timeout=5)
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    if raw is None:
                        raw = {}
                    if not isinstance(raw, dict):
                        raise LinkError("Persisted link state is invalid")
                    work = copy.copy(self)
                    work._db = None
                    work._links = {token: LinkRecord(**value) for token, value in raw.items()}
                    work._save = lambda: None
                    result = getattr(work, operation)(*args, **kwargs)
                    if operation in ("create", "consume", "revoke", "purge_expired"):
                        await connection.execute("""INSERT INTO agent_documents(name,value)
                            VALUES($1,$2::jsonb) ON CONFLICT(name) DO UPDATE
                            SET value=EXCLUDED.value,updated_at=now()""", key,
                            json.dumps({token: asdict(record) for token, record in work._links.items()}), timeout=5)
            # Reflect only a committed transaction; callers must still read SQL
            # afresh rather than treating this per-process cache as authority.
            self._links = work._links
            return result
        except LinkError:
            raise
        except Exception:
            logger.warning("Database link operation was not confirmed")
            raise LinkError("Link result was not confirmed; check before retrying") from None

    async def acreate(self, *args, **kwargs):
        return await self._atomic("create", *args, **kwargs)

    async def aresolve(self, token):
        return await self._atomic("resolve", token)

    async def aconsume(self, token, *, request_id=None):
        return await self._atomic("consume", token, request_id=request_id)

    async def arevoke(self, token, **kwargs):
        return await self._atomic("revoke", token, **kwargs)

    async def aowned(self, owner_id):
        return await self._atomic("owned", owner_id)

    async def apurge_expired(self):
        return await self._atomic("purge_expired")

    # -- signing -----------------------------------------------------------

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()[:16])

    def create(
        self,
        file_id: str,
        owner_id: int,
        *,
        ttl_hours: int | None = None,
        max_uses: int = 0,
    ) -> LinkRecord:
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        # ``ttl_hours=0`` means "expires now"; only None falls back to the default.
        hours = self.default_ttl // 3600 if ttl_hours is None else ttl_hours
        ttl = hours * 3600
        # Independent grants must never overwrite each other's caps/revocation.
        # 48 ASCII bytes; link_ payload=53 and link:revoke: callback=60.
        payload = f"v2_{secrets.token_urlsafe(16)}"
        token = f"{payload}_{self._sign(payload)}"
        record = LinkRecord(
            token=token,
            file_id=file_id,
            owner_id=int(owner_id),
            created_at=time.time(),
            expires_at=time.time() + ttl,
            max_uses=max(0, int(max_uses or 0)),
        )
        self._links[token] = record
        try:
            self._save()
        except Exception:
            self._links.pop(token, None)
            raise
        return record

    def resolve(self, token: str) -> LinkRecord:
        """Return the record for *token*, or raise :class:`LinkError`."""
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        record = self._links.get(token)
        if record is not None:
            if record.revoked:
                raise LinkError("link revoked")
            if record.expired:
                raise LinkError("link expired")
            if record.exhausted:
                raise LinkError("link used up")
            return record

        # Signature validity cannot restore lost revocation or use-limit state.
        if not isinstance(token, str) or (not token.startswith("v2_") and len(token.split(".")) != 4):
            raise LinkError("malformed link")
        if not self.verify_signature(token):
            raise LinkError("bad signature")
        raise LinkError("link unavailable")

    def consume(self, token: str, *, request_id: str | None = None) -> LinkRecord:
        """Like :meth:`resolve`, incrementing the use counter.

        ``resolve`` has already refused a revoked, expired or exhausted link, so
        the increment below can only happen on a link that may still be used.
        """
        if request_id is not None and (not isinstance(request_id, str) or
                not re.fullmatch(r"-?[0-9]{1,20}:[0-9]{1,20}:[0-9]{1,20}", request_id)):
            raise LinkError("Invalid redemption request identity")
        record = self.resolve(token)
        stored = self._links.get(token)
        if stored is not None:
            if request_id is not None and request_id in stored.redemption_requests:
                raise LinkError("Redemption request already recorded")
            if request_id is not None:
                stored.redemption_requests.append(request_id)
            stored.uses += 1
            try:
                self._save()
            except Exception:
                stored.uses -= 1
                if request_id is not None:
                    stored.redemption_requests.remove(request_id)
                raise
        return record

    def get(self, token: str) -> LinkRecord | None:
        """The stored record for *token*, without validating it."""
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        return self._links.get(token)

    def revoke(self, token: str, *, owner_id: int | None = None) -> bool:
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        record = self._links.get(token)
        if record is None or record.revoked:
            return False
        if owner_id is not None and record.owner_id != owner_id:
            return False
        record.revoked = True
        try:
            self._save()
        except Exception:
            record.revoked = False
            raise
        return True

    def owned(self, owner_id: int) -> list[LinkRecord]:
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        return sorted(
            (r for r in self._links.values() if r.owner_id == owner_id),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def verify_signature(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) > 512 or not token.isascii():
            return False
        if token.startswith("v2_") and re.fullmatch(r"v2_[A-Za-z0-9_-]{22}_[A-Za-z0-9_-]{22}", token):
            payload, signature = token[:25], token[26:]
        else:
            # Legacy tokens are accepted only with their persisted grant record.
            parts = token.split(".")
            if len(parts) != 4:
                return False
            payload, signature = ".".join(parts[:3]), parts[3]
        try:
            _unb64(signature)
        except (binascii.Error, ValueError):
            return False
        return hmac.compare_digest(self._sign(payload), signature)

    def purge_expired(self) -> int:
        """Drop records whose expiry has passed. Returns how many were removed."""
        if self._db is not None:
            raise LinkError("Awaited Database link operation required")
        stale = [token for token, record in self._links.items() if record.expired]
        for token in stale:
            self._links.pop(token, None)
        if stale:
            self._save()
        return len(stale)
