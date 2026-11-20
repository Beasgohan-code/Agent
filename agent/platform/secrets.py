"""Agent — secrets at rest: clone tokens are encrypted, not just masked.

A masked token in a Telegram panel protects the screen, not the database. The
clone store keeps the one credential that can take over somebody's bot, so it is
written as ciphertext: Fernet (AES-128-CBC + HMAC-SHA256, versioned) with a key
from ``TOKEN_KEY``.

Four rules this module actually enforces:

* a key that cannot be used is an **error**, never a silent downgrade to
  plaintext — a deployment that thinks it encrypts and does not is worse than one
  that knows it does not;
* no key permits legacy plaintext reads but refuses new credential writes;
* ciphertext carries a ``v1:`` prefix, so the format can change and old rows stay
  readable;
* decryption failure is its own exception: a rotated key must not be mistaken for
  a corrupt record.
"""

from __future__ import annotations

import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

#: Marks a value this module produced; plaintext values have no prefix.
PREFIX = "v1:"


class SecretError(RuntimeError):
    """Encryption is configured but unusable, or a value cannot be decrypted."""


def _fernet_module():
    """The ``cryptography`` Fernet class, or ``None`` when it is not installed."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover - depends on the deployment image
        return None
    return Fernet


def normalise_key(raw: str | None) -> bytes | None:
    """``TOKEN_KEY`` → a Fernet key, or ``None`` when unset.

    Both acceptable shapes are accepted because both get pasted: a 44-character
    urlsafe-base64 Fernet key, and 64 hex characters (what ``openssl rand -hex``
    prints). Anything else is refused with a sentence that says how to make one.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) == 64:
        try:
            raw_bytes = bytes.fromhex(text)
        except ValueError:
            pass
        else:
            return base64.urlsafe_b64encode(hashlib.sha256(raw_bytes).digest())
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise SecretError(
            "TOKEN_KEY is not a Fernet key. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"`.'
        ) from exc
    if len(decoded) != 32:
        raise SecretError(
            "TOKEN_KEY must decode to 32 bytes. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"`.'
        )
    return base64.urlsafe_b64encode(decoded)


class SecretBox:
    """Encrypts and decrypts the values a store must keep at rest."""

    def __init__(self, key: str | None, *, what: str = "TOKEN_KEY") -> None:
        self._key = normalise_key(key)
        self._what = what
        self._fernet = None
        if self._key is not None:
            module = _fernet_module()
            if module is None:
                # Loud on purpose: the deployment asked for encryption and the
                # image cannot provide it. Callers turn this into a refusal.
                raise SecretError(
                    f"{what} is set but the `cryptography` package is not installed. "
                    "Install it (it is in requirements.txt); do not remove the key to bypass encryption."
                )
            self._fernet = module(self._key)
        else:
            logger.warning(
                "%s is not set: secret writes are disabled. Configure a key to "
                "encrypt credentials at rest.",
                what,
            )

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    # -- values ------------------------------------------------------------
    def encrypt(self, value: str) -> str:
        """Ciphertext for *value*; never silently downgrade to plaintext."""
        text = "" if value is None else str(value)
        if not text:
            return text
        if self._fernet is None:
            raise SecretError(f'{self._what} is required to write credentials.')
        token = self._fernet.encrypt(text.encode()).decode()
        return PREFIX + token

    def decrypt(self, value: str) -> str:
        """The plaintext of *value*, tolerating rows written before encryption."""
        text = "" if value is None else str(value)
        if not text:
            return text
        if not text.startswith(PREFIX):
            return text          # a legacy plaintext row, or an unencrypted build
        if self._fernet is None:
            raise SecretError(
                f"This record is encrypted but {self._what} is not set; the "
                "deployment cannot read it."
            )
        try:
            return self._fernet.decrypt(text[len(PREFIX) :].encode()).decode()
        except Exception as exc:  # noqa: BLE001 - any failure is the same answer
            raise SecretError(
                "Could not decrypt this record: the key does not match the one it "
                "was written with."
            ) from exc

    def is_ciphertext(self, value: str) -> bool:
        return str(value or "").startswith(PREFIX)


def box_from(settings) -> SecretBox:
    """The box a deployment's settings describe."""
    return SecretBox(getattr(settings, "token_key", None))
