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


#: Primary optional features plus the platform controls. Mandatory group core
#: is added by module selection and does not consume optional slots.
DEFAULT_PLUGINS: tuple[str, ...] = (
    "ops",
    "core",
    "clone",
    "filestore",
    "leech",
    "linkshare",
    "moderation",
    "music",
    "postmaker",
    "encoder",
    "ai_agent",
)


def _plugins(raw: str | None) -> tuple[str, ...]:
    """``PLUGINS=a,b`` narrows the build; ``*`` registers everything compiled."""
    text = (raw or "").strip()
    if not text:
        return DEFAULT_PLUGINS
    if text == "*":
        return ("*",)
    names = tuple(
        dict.fromkeys(part.strip().lower() for part in text.split(",") if part.strip())
    )
    return names or DEFAULT_PLUGINS


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings."""

    bot_token: str = field(repr=False)
    api_id: int
    api_hash: str = field(repr=False)
    session_name: str = "agent"
    # Optional operational knobs; every one has a working default.
    data_dir: Path = field(default_factory=lambda: Path("data"))
    #: Derived from the bot token so links stay valid across restarts without
    #: introducing another required variable.
    link_secret: str = field(default="", repr=False)
    #: Optional. Until it is set, owner-only commands refuse politely instead
    #: of guessing who owns the bot.
    owner_id: int | None = None
    #: Default log channel; /setlog overrides it at runtime.
    log_channel: int | None = None
    #: Publish active Telegram commands on start/changes (SYNC_COMMANDS=0 disables).
    sync_commands: bool = True
    #: Optional MTProto user session for voice-chat streaming (SESSION_STRING).
    #: A bot token cannot join a group call, so the player needs its own session.
    #: Never logged, never written to disk here.
    session_string: str | None = field(default=None, repr=False)
    #: Picture shown above /start — a URL or a path this process can read.
    #: START_IMAGE=0 removes it. Nothing depends on it: an unreachable image
    #: falls back to the plain text screen.
    start_image: str | None = None
    #: PostgreSQL DSN (DATABASE_URL). None keeps the JSON files.
    database_url: str | None = field(default=None, repr=False)
    #: How many clones this deployment will run at once (CLONE_LIMIT).
    clone_limit: int = 5
    #: The Telegram bot id inside the token: every stored row is scoped by it.
    bot_id: int = 0
    #: Which rows this instance owns. ``main:<bot id>`` for the bot itself;
    #: :meth:`agent.modules.clone.manager.CloneManager.settings_for` overrides it
    #: with ``clone:<bot id>`` so two bots sharing one database never collide.
    db_scope: str = "global"
    #: TOKEN_KEY: the Fernet key clone tokens are encrypted with at rest.
    token_key: str | None = field(default=None, repr=False)
    #: STORAGE_CHANNEL: a private channel id the bot archives files into. With it,
    #: the vault survives a redeploy: delivery re-uses Telegram's own file_id.
    storage_channel: int | None = None
    #: DB_REQUIRED=1 makes an unreachable DATABASE_URL a startup failure instead
    #: of a quiet fall back to JSON files.
    db_required: bool = True
    #: Which plugins register at startup (PLUGINS=..., or * for every module).
    plugins: tuple[str, ...] = DEFAULT_PLUGINS
    ai_api_key: str | None = field(default=None, repr=False)
    ai_model: str | None = None
    keepalive_origin: str | None = None
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
            start_image=_optional_image(source.get("START_IMAGE")),
            session_string=(source.get("SESSION_STRING") or "").strip() or None,
            plugins=_plugins(source.get("PLUGINS")),
            clone_limit=_bounded_int(source.get("CLONE_LIMIT"), 5, 0, 50),
            bot_id=_bot_id(bot_token),
            db_scope=f"main:{_bot_id(bot_token)}",
            token_key=(source.get("TOKEN_KEY") or "").strip() or None,
            storage_channel=_optional_chat(source.get("STORAGE_CHANNEL")),
            db_required=True,  # PostgreSQL-only runtime; DB_REQUIRED=0 no longer enables disk state.
            database_url=(source.get("DATABASE_URL") or "").strip() or None,
            ai_api_key=(source.get("AI_API_KEY") or "").strip() or None,
            ai_model=(source.get("AI_MODEL") or "").strip() or None,
            keepalive_origin=(source.get("RENDER_EXTERNAL_URL") or "").strip() or None,
            health_port=_optional_port(source),
            watchdog_interval=_optional_float(source.get("WATCHDOG_INTERVAL_SECONDS"), 30.0),
            watchdog_timeout=_optional_float(source.get("WATCHDOG_TIMEOUT_SECONDS"), 20.0),
            watchdog_fatal_after=int(
                _optional_float(source.get("WATCHDOG_FATAL_AFTER"), 5.0)
            ),
        )


def _bot_id(token: str) -> int:
    """The id inside ``<id>:<secret>``; ``0`` when it cannot be read."""
    head, _, _ = (token or "").partition(":")
    try:
        value = int(head)
    except ValueError:
        return 0
    return value if value > 0 else 0


#: The picture the owner asked for. Kept in code so a fresh deploy looks right
#: without another environment variable; START_IMAGE overrides it and
#: START_IMAGE=0 turns the picture off.
DEFAULT_START_IMAGE = "https://files.catbox.moe/dhajpx.jpg"


def _optional_image(raw: str | None) -> str | None:
    """``START_IMAGE`` as a URL or path; ``None`` disables the picture."""
    value = (DEFAULT_START_IMAGE if raw is None else str(raw)).strip()
    return None if value.lower() in ("", "0", "false", "no", "off", "none") else value


def _optional_chat(raw: str | None) -> int | None:
    """A chat id: negative for groups and channels, which ``_optional_id`` refuses."""
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value != 0 else None


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


def _bounded_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    """A small integer from the environment, clamped, never raised over."""
    try:
        value = int((raw or "").strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


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
