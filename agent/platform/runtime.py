"""Runtime plugin control: enable, disable and restart, for real.

Pyrogram lets a handler be removed again, so disabling a plugin detaches its
handlers instead of merely setting a flag that later code forgets to check.
State is persisted so a disabled plugin stays disabled across restarts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .policy import PROTECTED_PLUGINS

logger = logging.getLogger(__name__)

#: The shell and group-management core cannot be switched off.
PROTECTED = PROTECTED_PLUGINS


class PluginRuntime:
    """Tracks which handlers belong to which plugin and switches them on/off."""

    def __init__(
        self,
        registry,
        *,
        state_path: Path | None = None,
        protected: tuple[str, ...] = PROTECTED,
        db=None,
    ) -> None:
        self.registry = registry
        self.state_path = Path(state_path) if state_path else None
        self._db = db
        self.protected = tuple(dict.fromkeys((*PROTECTED, *protected)))
        self._handlers: dict[str, list[tuple[Any, int]]] = {}
        self._client = None
        self._disabled: set[str] = set()
        self.change_hook: Callable[[], None] | None = None
        self.restart_hook: Callable[[], None] | None = None
        self.restart_requested = False
        self.restart_reason = ""
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if self._db is not None and getattr(self._db, "connected", False):
            data = self._db.get("runtime")
        elif self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("plugin state unreadable; assuming defaults")
                return
        else:
            return
        disabled = data.get("disabled") if isinstance(data, dict) else None
        if isinstance(disabled, list):
            self._disabled = {str(slug) for slug in disabled}

    def _save(self) -> None:
        if self._db is not None and getattr(self._db, "connected", False):
            self._db.save("runtime", {"disabled": sorted(self._disabled)})
            return
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"disabled": sorted(self._disabled)}, indent=2), encoding="utf-8"
        )

    # -- wiring ------------------------------------------------------------

    def attach(self, client) -> None:
        self._client = client

    def track(self, slug: str, handler, group: int = 0) -> None:
        self._handlers.setdefault(slug, []).append((handler, group))

    def wants_disabled(self, slug: str) -> bool:
        return slug not in self.protected and slug in self._disabled

    # -- control -----------------------------------------------------------

    def hydrate(self) -> None:
        """Re-read the disabled set; called once PostgreSQL has been loaded."""
        self._disabled = set()
        self._load()

    def is_protected(self, slug: str) -> bool:
        return slug in self.protected

    def disable(self, slug: str) -> bool:
        """Detach every handler of *slug*. False when it is protected/unknown."""
        if self.is_protected(slug):
            raise ValueError(f"{slug!r} cannot be disabled")
        if slug not in self._handlers and not self.registry.is_enabled(slug):
            return False
        if self._client is not None:
            for handler, group in self._handlers.get(slug, []):
                try:
                    self._client.remove_handler(handler, group)
                except Exception:  # noqa: BLE001 - already gone
                    logger.debug("handler for %s was not registered", slug)
        self.registry.disable(slug)
        self._disabled.add(slug)
        self._save()
        self._notify_change()
        return True

    def enable(self, slug: str) -> bool:
        """Re-attach the handlers recorded for *slug*."""
        if slug not in self._handlers:
            return False
        if self._client is not None:
            for handler, group in self._handlers[slug]:
                self._client.add_handler(handler, group)
        self.registry.enable(slug)
        self._disabled.discard(slug)
        self._save()
        self._notify_change()
        return True

    def _notify_change(self):
        if self.change_hook is not None:
            try:
                self.change_hook()
            except Exception:
                logger.warning("Plugin change notification failed; handlers remain updated.")

    def state(self) -> list[dict]:
        rows = []
        for manifest in self.registry.manifests():
            enabled = self.registry.is_enabled(manifest.slug)
            rows.append(
                {
                    "slug": manifest.slug,
                    "name": manifest.name,
                    "enabled": enabled,
                    "commands": list(manifest.commands),
                    "description": manifest.description,
                    "scope": manifest.scope,
                    "protected": self.is_protected(manifest.slug),
                }
            )
        return rows

    def request_restart(self, reason: str = "requested") -> bool:
        """Ask the process to stop so its supervisor can start it again."""
        self.restart_requested = True
        self.restart_reason = reason
        if self.restart_hook is None:
            return False
        self.restart_hook()
        return True
