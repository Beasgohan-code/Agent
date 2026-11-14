"""Agent — configuration loaded from the environment.

Required environment variables (and nothing else):

    BOT_TOKEN   from @BotFather
    API_ID      from https://my.telegram.org
    API_HASH    from https://my.telegram.org
"""

from __future__ import annotations

import os
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class ConfigError(RuntimeError):
    """Raised when the environment does not describe a runnable bot."""


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings."""

    bot_token: str
    api_id: int
    api_hash: str
    session_name: str = "agent"
    # Optional operational knobs; every one has a working default.
    data_dir: Path = field(default_factory=lambda: Path("data"))
    #: Derived from the bot token so links stay valid across restarts without
    #: introducing another required variable.
    link_secret: str = ""
    #: Optional. Until it is set, owner-only commands refuse politely instead
    #: of guessing who owns the bot.
    owner_id: int | None = None
    #: Default log channel; /setlog overrides it at runtime.
    log_channel: int | None = None
    #: Publish the command list to Telegram on start (SYNC_COMMANDS=0 disables).
    sync_commands: bool = True
    health_port: int | None = None
    watchdog_interval: float = 30.0
    watchdog_timeout: float = 20.0
    watchdog_fatal_after: int = 5

    @property
    def masked_token(self) -> str:
        """Token with the secret half hidden, safe to write to logs."""
        prefix, _, _ = self.bot_token.partition(":")
        return f"{prefix}:{'-' * 8}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from *env* (defaults to ``os.environ``).

        Every problem is reported at once so a misconfigured deploy does not
        need one restart per missing variable.
        """
        source = os.environ if env is None else env
        problems: list[str] = []

        bot_token = (source.get("BOT_TOKEN") or "").strip()
        if not bot_token:
            problems.append("BOT_TOKEN is missing (get it from @BotFather).")
        elif not BOT_TOKEN_RE.match(bot_token):
            problems.append(
                "BOT_TOKEN is malformed; expected '<digits>:<secret>' as issued by @BotFather."
            )

        raw_api_id = (source.get("API_ID") or "").strip()
        api_id = 0
        if not raw_api_id:
            problems.append("API_ID is missing (from https://my.telegram.org).")
        else:
            try:
                api_id = int(raw_api_id)
            except ValueError:
                problems.append("API_ID must be an integer, got a non-numeric value.")
            else:
                if api_id <= 0:
                    problems.append("API_ID must be a positive integer.")

        api_hash = (source.get("API_HASH") or "").strip()
        if not api_hash:
            problems.append("API_HASH is missing (from https://my.telegram.org).")
        elif not API_HASH_RE.match(api_hash):
            problems.append("API_HASH must be 32 hexadecimal characters.")

        if problems:
            raise ConfigError(
                "Invalid environment configuration:\n  - " + "\n  - ".join(problems)
            )

        return cls(
            bot_token=bot_token,
            api_id=api_id,
            api_hash=api_hash,
            data_dir=Path((source.get("DATA_DIR") or "data").strip() or "data"),
            link_secret=hashlib.sha256(bot_token.encode()).hexdigest(),
            owner_id=_optional_id(source.get("OWNER_ID")),
            log_channel=_optional_id(source.get("LOG_CHANNEL")),
            sync_commands=(source.get("SYNC_COMMANDS") or "1").strip().lower()
            not in ("0", "false", "no", "off"),
            health_port=_optional_port(source),
            watchdog_interval=_optional_float(source.get("WATCHDOG_INTERVAL_SECONDS"), 30.0),
            watchdog_timeout=_optional_float(source.get("WATCHDOG_TIMEOUT_SECONDS"), 20.0),
            watchdog_fatal_after=int(
                _optional_float(source.get("WATCHDOG_FATAL_AFTER"), 5.0)
            ),
        )


def _optional_id(raw: str | None) -> int | None:
    """A Telegram user id, or ``None`` when unset or unparseable."""
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _optional_float(raw: str | None, default: float) -> float:
    try:
        value = float((raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_port(env: Mapping[str, str]) -> int | None:
    """``HEALTH_PORT`` wins; a platform-provided ``PORT`` enables it too.

    Returns ``None`` when neither is usable, which keeps the bot a pure
    background worker with no HTTP server.
    """
    for key in ("HEALTH_PORT", "PORT"):
        raw = (env.get(key) or "").strip()
        if not raw:
            continue
        try:
            port = int(raw)
        except ValueError:
            continue
        if 0 < port < 65536:
            return port
    return None
