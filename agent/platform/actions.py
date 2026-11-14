"""Agent — a tiny router for component presses owned by modules.

The callback handler started life with three static screens. Modules now need
buttons too (member verification), so each module registers a *prefix* instead of
having its data hard-coded in the UI layer. Prefixes cannot collide: registering
the same one twice raises, which is how a bot ends up with one owner per button.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

#: ``client, callback_query, rest`` where *rest* is everything after ``prefix:``.
ActionHandler = Callable[[object, object, str], Awaitable[None]]


class ActionRouter:
    """Maps ``prefix:...`` callback data to a module handler."""

    def __init__(self) -> None:
        self._routes: dict[str, ActionHandler] = {}

    def register(self, prefix: str, handler: ActionHandler) -> None:
        key = (prefix or "").strip().lower()
        if not key:
            raise ValueError("an action prefix cannot be empty")
        if key in self._routes:
            raise ValueError(f"callback prefix {key!r} is already registered")
        self._routes[key] = handler

    def handles(self, data: str) -> bool:
        prefix, _, _ = (data or "").partition(":")
        return prefix in self._routes

    def prefixes(self) -> list[str]:
        return sorted(self._routes)

    async def dispatch(self, client, callback_query) -> bool:
        """Run the module handler for this press; False when nobody owns it."""
        data = getattr(callback_query, "data", "") or ""
        prefix, _, rest = data.partition(":")
        handler = self._routes.get(prefix)
        if handler is None:
            return False
        try:
            await handler(client, callback_query, rest)
        except Exception:  # noqa: BLE001 - a bad press must not stop the client
            logger.exception("Callback %r failed in its module", data)
        return True
