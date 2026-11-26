"""Agent — what ``/start <payload>`` means, owned by modules rather than the UI.

A deep link is the only way into a bot that is not a command: ``t.me/bot?start=x``
hands the payload to ``/start``, and from there the bot has one message to work
out what the user meant. Telegram apps use it for share links, invite codes and
verification tokens, and every one of those is a feature a module owns.

So the modules register a *prefix* (``link``, ``verify``, ``gift``) instead of
the start handler growing an ``if payload.startswith(...)`` ladder. Registering
a prefix twice raises, exactly like :class:`agent.platform.actions.ActionRouter`:
one payload, one owner.
"""

from __future__ import annotations

import logging
import asyncio
import re
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

#: Separator between the prefix and the rest: ``link_<token>``, ``verify_<id>``.
SEPARATOR = "_"

#: ``client, message, rest`` — the handler answers on its own.
DeepLinkHandler = Callable[[object, object, str], Awaitable[None]]


def split(payload: str) -> tuple[str, str]:
    """``link_abc.def`` → ``("link", "abc.def")``; ``junk`` → ``("", "junk")``.

    Telegram strips nothing from the payload, so the split is done on the first
    separator only: a token may contain anything, including more underscores.
    """
    text = (payload or "").strip()
    if not text:
        return "", ""
    prefix, sep, rest = text.partition(SEPARATOR)
    if not sep:
        return "", text
    return prefix.strip().lower(), rest.strip()


class DeepLinkRouter:
    """Maps the prefix of a ``/start`` payload to a module handler."""

    def __init__(self) -> None:
        self.gate = None
        self._routes: dict[str, DeepLinkHandler] = {}

    def register(self, prefix: str, handler: DeepLinkHandler) -> None:
        if not isinstance(prefix, str):
            raise ValueError("a deep-link prefix must be a string")
        key = prefix.strip().lower()
        if not key:
            raise ValueError("a deep-link prefix cannot be empty")
        if SEPARATOR in key:
            raise ValueError(f"deep-link prefix {key!r} cannot contain {SEPARATOR!r}")
        if not re.fullmatch(r"[a-z0-9-]+", key):
            raise ValueError("a deep-link prefix must contain letters, numbers or hyphens")
        if not callable(handler):
            raise ValueError("a deep-link handler must be callable")
        if key in self._routes:
            raise ValueError(f"deep-link prefix {key!r} is already registered")
        from .execution import REGISTERING
        owner = REGISTERING.get()
        if self.gate is not None and owner is not None:
            handler = self.gate.wrap(owner, handler)
        self._routes[key] = handler

    def prefixes(self) -> list[str]:
        return sorted(self._routes)

    def handles(self, payload: str) -> bool:
        prefix, _rest = split(payload)
        return prefix in self._routes

    async def dispatch(self, client, message, payload: str) -> bool:
        """Run the handler for *payload*; ``False`` when no module owns it.

        A handler that raises is logged and reported as handled: the user asked
        for something specific, and falling back to the welcome screen would
        hide the failure behind a greeting.
        """
        prefix, rest = split(payload)
        handler = self._routes.get(prefix)
        if handler is None:
            return False
        try:
            await handler(client, message, rest)
        except Exception as exc:
            # Tokens and raw provider error messages can contain private data.
            logger.error("Deep-link handler failed prefix=%s (%s)", prefix, type(exc).__name__)
            try:
                await asyncio.wait_for(message.reply(
                    "This link action was not confirmed. Check its result before retrying; contact the bot administrator if it keeps failing."
                ), timeout=5)
            except Exception as reply_error:
                logger.warning("Deep-link failure notice unavailable (%s)", type(reply_error).__name__)
        return True
