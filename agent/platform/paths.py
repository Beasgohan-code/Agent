"""Where this process may write.

The container runs unprivileged (uid 10001) while ``/app`` may belong to root,
so ``data/`` can be read-only. Failing at the first write — deep inside a
lease or a storage call — produces a confusing crash; resolving the location
once, up front, produces a clear warning instead.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

FALLBACK_NAME = "agent-data"


def is_writable(path: Path) -> bool:
    """True when *path* is a directory we can create files in."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_data_dir(preferred: Path) -> tuple[Path, bool]:
    """Return (directory, preferred_was_usable).

    The fallback is under the system temp directory. It is honest about what it
    is: writable, but ephemeral — links and stored files will not survive a
    restart, so the caller logs a warning rather than pretending otherwise.
    """
    preferred = Path(preferred)
    if is_writable(preferred):
        return preferred, True

    fallback = Path(tempfile.gettempdir()) / FALLBACK_NAME
    if is_writable(fallback):
        logger.warning(
            "DATA_DIR %s is not writable by uid %s; falling back to %s. "
            "Stored files, links and settings will NOT survive a restart — "
            "fix the volume permissions to keep them.",
            preferred,
            os.geteuid() if hasattr(os, "geteuid") else "?",
            fallback,
        )
        return fallback, False

    # Nothing is writable: run with the configured path and let the first
    # real write report the failure rather than inventing a third location.
    logger.error("No writable data directory found (tried %s and %s).", preferred, fallback)
    return preferred, False
