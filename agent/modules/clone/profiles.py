"""Profiles — how much of this bot a clone actually runs.

A clone has always been "this bot, on another token". That is the right default,
but it is not the only useful shape: most people who drop a token in want a file
bot, and handing them moderation, music and the deployment's own controls for no
reason is how one pasted token becomes a liability.

Three profiles, no new commands:

* ``standard`` — the deployment's own ``PLUGINS`` set. A clone behaves like this
  bot, which is what it did before profiles existed.
* ``files`` — the file machinery only: store, leech, links, rename, post. No
  moderation, no music, no clone-of-a-clone, no deployment controls.
* ``tiny`` — the shell alone (``core`` + ``ops``): ``/start``, ``/help``,
  ``/menu``, and nothing that touches storage or moderation.

``ops`` and ``clone`` are stripped from every restricted profile on purpose: a
clone whose owner is not this deployment's owner must not reach ``/plugin``,
``/db`` or ``/restart``, and a clone must never be able to mint more clones.
"""

from __future__ import annotations

#: Profile names, in the order the panel offers them.
STANDARD = "standard"
FILES = "files"
TINY = "tiny"
ORDER: tuple[str, ...] = (STANDARD, FILES, TINY)

#: What a file bot is used for. Mirrors ``WORKER`` thinking without the name.
FILE_PLUGINS: tuple[str, ...] = (
    "filestore",
    "leech",
    "linkshare",
    "renamer",
    "postmaker",
)

#: Nothing but the front door and the controls (both shells always register).
TINY_PLUGINS: tuple[str, ...] = ()

#: Never enabled by a restricted profile, whatever the environment says.
RESERVED: tuple[str, ...] = ("ops", "clone")


def clean(name: str | None) -> str:
    """A known profile name, defaulting to ``standard``."""
    text = (name or "").strip().lower()
    return text if text in ORDER else STANDARD


def plugins_for(profile: str | None, settings) -> tuple[str, ...]:
    """The plugin tuple a clone with *profile* runs.

    ``standard`` inherits the deployment's selection, so changing ``PLUGINS``
    re-tunes every standard clone instead of leaving them on an old copy.
    """
    name = clean(profile)
    if name == STANDARD:
        return tuple(getattr(settings, "plugins", ()) or ())
    if name == FILES:
        return FILE_PLUGINS
    return TINY_PLUGINS


def reserved(profile: str | None) -> tuple[str, ...]:
    """Plugins this profile refuses even if something else asks for them."""
    return () if clean(profile) == STANDARD else RESERVED


def label(profile: str | None) -> str:
    """A short human name for a table cell."""
    return {
        STANDARD: "standard",
        FILES: "files",
        TINY: "tiny",
    }[clean(profile)]


def describe(profile: str | None) -> str:
    """What the profile means, in one sentence."""
    return {
        STANDARD: "Runs the same plugins as this bot.",
        FILES: "File store, leech, links, rename and post only.",
        TINY: "Just /start, /help and /menu — nothing that touches files.",
    }[clean(profile)]


def summary(profile: str | None, settings) -> str:
    """``"7 plugins"`` — what the profile actually registers, counted."""
    plugins = plugins_for(profile, settings)
    if plugins == ("*",):
        return "every plugin"
    count = len({name for name in plugins} | {"core", "ops"})
    return f"{count} plugins"
