"""Where clones are recorded, and what a record may say.

A clone is one bot token plus the person who added it. Tokens and optional AI
provider keys are secrets, so the file is written ``0600``, the panel never shows
more than its first digits, and credential writes require encryption with
``TOKEN_KEY`` (:mod:`agent.platform.secrets`). Masking is a screen
concern; encryption is a database concern, and this store needs both.

Records written before encryption existed still load: a plaintext token is read
as-is and the next save rewrites the record as ciphertext.

Records are keyed by the bot id inside the token, not by owner: Telegram already
decides that a token identifies one bot, and two records for one bot would be
two clients answering the same updates.
"""

from __future__ import annotations

import logging
import copy
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...platform.db import load_document, save_document
from ...platform.secrets import SecretBox, SecretError

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
    token: str = field(repr=False)
    username: str = ""
    name: str = ""
    created_at: float = field(default_factory=time.time)
    #: Set when an owner parks a clone; it stays in the list but is not started.
    disabled: bool = False
    #: How much of this bot the clone runs: ``standard``, ``files`` or ``tiny``
    #: (see :mod:`agent.modules.clone.profiles`). Empty means ``standard``.
    profile: str = "standard"
    selected_plugins: tuple[str, ...] = ()
    ai_api_key: str | None = field(default=None, repr=False)
    ai_model: str | None = None
    assistant_session: str | None = field(default=None, repr=False)
    managed_owner: bool = False
    log_channel: int | None = None
    storage_channel: int | None = None
    configuration_revision: int = 0

    @property
    def handle(self) -> str:
        return f"@{self.username}" if self.username else f"bot {self.bot_id}"

    @property
    def masked(self) -> str:
        """Enough of the token to recognise it, never enough to use it."""
        return f"{self.bot_id}:{self.token.split(':', 1)[-1][:4]}…"

    def as_json(self) -> dict:
        """The record as plain data. Contains the token: never persist this.

        :meth:`CloneStore._payload` is what gets written; it swaps the token for
        ciphertext when a key is configured.
        """
        return asdict(self)


class CloneStore:
    """A JSON list of clones, rewritten atomically on every change."""

    def __init__(
        self, root: str | Path, *, db=None, box: SecretBox | None = None
    ) -> None:
        self.path = Path(root) / "clones.json"
        #: With a database, clone records survive a redeploy on any instance.
        self._db = db
        #: Token encryption at rest; no key permits legacy reads only.
        self._box = box if box is not None else SecretBox(None)
        #: Set when a plaintext record was read and should be rewritten.
        self._needs_rewrite = False
        self._items: dict[int, Clone] = self._load()
        if self._db is None and self._box.enabled and self._needs_rewrite and self._items:
            # A record read in the old plaintext shape is rewritten encrypted,
            # so a deployment that adds TOKEN_KEY does not keep old rows naked.
            self._needs_rewrite = False
            self._save()
            logger.info(
                "Encrypted %d clone record(s) that predate TOKEN_KEY", len(self._items)
            )

    # -- persistence ------------------------------------------------------
    def _load(self) -> dict[int, Clone]:
        raw = load_document(self._db, "clones", self.path, [])
        return self._decode(raw)

    def _decode(self, raw):
        if raw == []:
            return {}
        items: dict[int, Clone] = {}
        for entry in raw if isinstance(raw, list) else []:
            try:
                # ``token_enc`` is the encrypted form; ``token`` is what older
                # records carry and what an unkeyed deployment still writes.
                stored = entry.get("token_enc") or entry.get("token") or ""
                try:
                    token = self._box.decrypt(str(stored))
                except SecretError:
                    logger.error(
                        "clone %s cannot be decrypted with this TOKEN_KEY; skipping it",
                        entry.get("bot_id"),
                    )
                    continue
                if entry.get("token") and not entry.get("token_enc"):
                    self._needs_rewrite = True
                ai_key = None
                if entry.get("ai_api_key_enc"):
                    try:
                        ai_key = self._box.decrypt(str(entry["ai_api_key_enc"]))
                    except SecretError:
                        logger.error(
                            "clone AI credential cannot be decrypted; skipping record"
                        )
                        continue
                assistant_session = None
                if entry.get("assistant_session_enc"):
                    try:
                        assistant_session = self._box.decrypt(
                            str(entry["assistant_session_enc"])
                        )
                    except SecretError:
                        logger.error(
                            "clone assistant credential cannot be decrypted; skipping record"
                        )
                        continue
                clone = Clone(
                    bot_id=int(entry["bot_id"]),
                    owner_id=int(entry["owner_id"]),
                    token=token,
                    username=str(entry.get("username") or ""),
                    name=str(entry.get("name") or ""),
                    created_at=float(entry.get("created_at") or 0.0),
                    disabled=bool(entry.get("disabled")),
                    profile=str(entry.get("profile") or "standard"),
                    selected_plugins=tuple(entry.get("selected_plugins") or ()),
                    assistant_session=assistant_session,
                    ai_api_key=ai_key,
                    ai_model=entry.get("ai_model"),
                    managed_owner=bool(entry.get("managed_owner")),
                    log_channel=entry.get("log_channel"),
                    storage_channel=entry.get("storage_channel"),
                    configuration_revision=int(entry.get("configuration_revision", 0)),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("skipping a malformed clone record")
                continue
            items[clone.bot_id] = clone
        return items

    @staticmethod
    def _payload(clone: Clone, box: SecretBox) -> dict:
        """The record as it is written: the token swapped for its ciphertext."""
        data = clone.as_json()
        token = data.pop("token", "")
        session = data.pop("assistant_session", None)
        if session:
            if not box.enabled:
                raise SecretError("Assistant sessions require TOKEN_KEY.")
            data["assistant_session_enc"] = box.encrypt(str(session))
        ai_key = data.pop("ai_api_key", None)
        if ai_key:
            if not box.enabled:
                raise SecretError("AI clone credentials require TOKEN_KEY.")
            data["ai_api_key_enc"] = box.encrypt(str(ai_key))
        if not box.enabled:
            raise SecretError('Clone token writes require TOKEN_KEY.')
        data["token_enc"] = box.encrypt(str(token))
        return data

    def _save(self) -> None:
        if self._db is not None:
            raise RuntimeError("Awaited PostgreSQL clone operation required")
        save_document(
            self._db,
            "clones",
            self.path,
            [self._payload(clone, self._box) for clone in self._items.values()],
        )

    async def _atomic(
        self, operation, *args, owner_limit=None, total_limit=None, **fields
    ):
        """Await canonical document mutations under a tenant transaction lock.

        All writers must use this API. Corrupt/undecryptable records abort the
        entire mutation rather than freeing capacity or deleting hidden rows.
        This compatibility bridge preserves the existing encrypted wire format.
        """
        if self._db is None:
            if operation == "add" and (
                len(self.by_owner(args[0].owner_id)) >= owner_limit
                or self.count() >= total_limit
            ):
                raise RuntimeError("Clone capacity reached")
            return getattr(self, operation)(*args, **fields)
        db = self._db
        if not db.connected or getattr(db, "_pool", None) is None:
            raise RuntimeError("PostgreSQL clone state unavailable")
        if not self.encrypted():
            raise RuntimeError("Clone database operations require TOKEN_KEY")
        if "clones" in getattr(db, "_pending", {}):
            raise RuntimeError("Legacy clone write pending; flush before retrying")
        try:
            async with db._pool.acquire(timeout=5) as conn:
                async with conn.transaction():
                    key = db.name_for("clones")
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        key,
                        timeout=5,
                    )
                    raw = await conn.fetchval(
                        "SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE",
                        key,
                        timeout=5,
                    )
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    raw = [] if raw is None else raw
                    if not isinstance(raw, list):
                        raise RuntimeError("Persisted clone state invalid")
                    work = copy.copy(self)
                    work._db = None
                    work._items = work._decode(raw)
                    if len(work._items) != len(raw):
                        raise RuntimeError(
                            "Clone records invalid or undecryptable; operation refused"
                        )
                    work._save = lambda: None
                    if operation == "add":
                        if (
                            len(work.by_owner(args[0].owner_id)) >= owner_limit
                            or work.count() >= total_limit
                        ):
                            raise RuntimeError("Clone capacity reached")
                    if operation == "update" and set(fields) - {
                        "username",
                        "disabled",
                        "profile",
                        "selected_plugins",
                        "ai_api_key",
                        "ai_model",
                        "assistant_session",
                    }:
                        raise RuntimeError("Clone identity fields cannot be updated")
                    result = getattr(work, operation)(*args, **fields)
                    if operation == "add":
                        if getattr(self, 'configuration', None) is None:
                            raise RuntimeError("Canonical configuration validator unavailable")
                        result, _ = await self.configuration._persist(conn, result, expected_revision=0,
                            request_id='creation', identity='creation')
                        work._items[args[0].bot_id] = result
                    if operation != "all":
                        await conn.execute(
                            """INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)
                            ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",
                            key,
                            json.dumps(
                                [
                                    self._payload(c, self._box)
                                    for c in work._items.values()
                                ]
                            ),
                            timeout=5,
                        )
            self._items = work._items
            return result
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(
                "Clone result not confirmed; check before retrying"
            ) from None

    async def aadd(self, clone, *, owner_limit, total_limit):
        if (
            type(owner_limit) is not int
            or type(total_limit) is not int
            or min(owner_limit, total_limit) < 1
        ):
            raise RuntimeError("Clone capacity unavailable")
        return await self._atomic(
            "add", clone, owner_limit=owner_limit, total_limit=total_limit
        )

    async def aupdate(self, bot_id, **fields):
        if self._db is not None:
            from .configuration import CONFIG_FIELDS
            if set(fields) & CONFIG_FIELDS:
                raise RuntimeError("Configuration changes require expected revision and request identity")
        return await self._atomic("update", bot_id, **fields)

    async def aremove(self, bot_id):
        return await self._atomic("remove", bot_id)

    async def aall(self):
        return await self._atomic("all")

    # -- reads ------------------------------------------------------------
    def get(self, bot_id: int) -> Clone | None:
        return self._items.get(int(bot_id))

    def all(self) -> tuple[Clone, ...]:
        return tuple(
            sorted(
                self._items.values(), key=lambda clone: clone.created_at, reverse=True
            )
        )

    def by_owner(self, owner_id: int) -> tuple[Clone, ...]:
        return tuple(c for c in self.all() if c.owner_id == int(owner_id))

    def count(self) -> int:
        return len(self._items)

    # -- writes -----------------------------------------------------------
    def add(self, clone: Clone) -> Clone:
        if self._db is not None:
            raise RuntimeError("Awaited PostgreSQL clone operation required")
        if clone.bot_id in self._items:
            raise ValueError(
                "This bot is already recorded; ownership cannot be overwritten"
            )
        self._items[clone.bot_id] = clone
        try:
            self._save()
        except Exception:
            self._items.pop(clone.bot_id, None)
            raise
        return clone

    def token_of(self, bot_id: int) -> str:
        """The decrypted token for *bot_id* (``""`` when unknown)."""
        clone = self._items.get(int(bot_id))
        return clone.token if clone else ""

    def encrypted(self) -> bool:
        """Whether this store writes ciphertext."""
        return self._box.enabled

    def update(self, bot_id: int, **fields) -> Clone | None:
        if self._db is not None:
            raise RuntimeError("Awaited PostgreSQL clone operation required")
        clone = self._items.get(int(bot_id))
        if clone is None:
            return None
        previous = copy.deepcopy(clone)
        for key, value in fields.items():
            if hasattr(clone, key):
                setattr(clone, key, value)
        try:
            self._save()
        except Exception:
            self._items[int(bot_id)] = previous
            raise
        return clone

    def remove(self, bot_id: int) -> bool:
        if self._db is not None:
            raise RuntimeError("Awaited PostgreSQL clone operation required")
        previous = self._items.pop(int(bot_id), None)
        if previous is None:
            return False
        try:
            self._save()
        except Exception:
            self._items[int(bot_id)] = previous
            raise
        return True
