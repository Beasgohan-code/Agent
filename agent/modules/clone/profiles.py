"""Profiles — how much of this bot a clone actually runs.

Profiles select optional features, not whether a bot can protect groups.
The shell and mandatory group-management core are added by module selection.

* ``standard`` — deployment-selected optional features.
* ``files`` — file store, leech, links, rename and post.
* ``tiny`` — no optional features.

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
        requested = tuple(getattr(settings, "plugins", ()) or ())
        if requested == ("*",):
            from ...modules import ORDER as modules
            requested = modules
        # Never allow a clone to mint more clones in the same parent process.
        return tuple(slug for slug in requested if slug != "clone")
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
        FILES: "Group core plus file store, leech, links, rename and post.",
        TINY: "Group core and navigation, without optional tools.",
    }[clean(profile)]


def summary(profile: str | None, settings) -> str:
    """``"7 plugins"`` — what the profile actually registers, counted."""
    plugins = plugins_for(profile, settings)
    if plugins == ("*",):
        return "every plugin"
    from ...platform.policy import PROTECTED_PLUGINS
    count = len(set(plugins) - set(PROTECTED_PLUGINS) - {"clone"})
    return f"Group Management + {count} tools" if count else "Group Management"
