"""Security — member verification, from Meikoagent's ``security`` plugin.

A new member is muted on arrival and asked to press one button. When they press
it, the mute is lifted. If they never press it, they are removed after the
configured timeout. That is the whole feature, and every part of it is real:
a restriction Telegram applies, a button Telegram delivers, a timer this process
holds, and a removal Telegram performs.

Deliberate limits, stated rather than implied:

* the pending set lives in memory — a restart forgets who was mid-verification
  (their mute stays, because Telegram keeps it; an administrator can lift it);
* verification is **off** by default and switches on with ``/verify on``;
* ``/lockdown`` already exists in the group module and is not duplicated here.
"""

from __future__ import annotations

import logging

from pyrogram.handlers import ChatMemberUpdatedHandler

from ...platform.actions import ActionRouter
from ...platform.manifest import PluginManifest
from .verify import (  # noqa: F401 - re-exported: one place to import verification from
    DEFAULT_TIMEOUT_MINUTES,
    MAX_TIMEOUT_MINUTES,
    PREFIX,
    Verifier,
    button_for,
    enabled,
    parse_press,
    timeout_minutes,
)

__all__ = [
    "DEFAULT_TIMEOUT_MINUTES",
    "MANIFEST",
    "MAX_TIMEOUT_MINUTES",
    "PREFIX",
    "Verifier",
    "build",
    "button_for",
    "enabled",
    "extra_handlers",
    "parse_press",
    "timeout_minutes",
    "verifier",
]

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="security",
    name="Security & verification",
    version="1.0.0",
    description="Mute new members until they press a button; remove them if they never do.",
    commands=("verify",),
    permissions=("messages.send", "chats.restrict", "chats.ban"),
    scope="group",
)


def verifier(ctx) -> Verifier:
    """The one Verifier for this context (built once by :func:`build`)."""
    existing = getattr(ctx, "verifier", None)
    if existing is None:
        existing = Verifier(ctx)
        ctx.verifier = existing
        router = getattr(ctx, "actions", None)
        if isinstance(router, ActionRouter):
            router.register(PREFIX, existing.on_press)
    return existing


def build(ctx):
    """Wire ``/verify`` and share one :class:`Verifier` with the watcher."""
    instance = verifier(ctx)
    return MANIFEST, {"verify": instance.verify}


def extra_handlers(ctx):
    """The join watcher that mutes unverified members."""
    instance = verifier(ctx)
    return [ChatMemberUpdatedHandler(instance.on_member_update)]
