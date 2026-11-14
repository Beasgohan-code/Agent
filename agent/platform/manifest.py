"""Agent — plugin manifest and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass(frozen=True)
class PluginManifest:
    """Static description of a module."""

    slug: str
    name: str
    version: str
    description: str
    commands: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    config_schema: dict = field(default_factory=dict)
    #: Where the commands may run: "private", "group" or "all". Moderation has
    #: no meaning in a private chat, so the scope is declared, not guessed.
    scope: str = "private"


@dataclass
class RegisteredPlugin:
    manifest: PluginManifest
    handlers: dict[str, Callable] = field(default_factory=dict)
    enabled: bool = True


class PluginRegistry:
    """Owns enabled/disabled state and the command → handler map."""

    def __init__(self) -> None:
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._command_owner: dict[str, str] = {}

    # -- installation ------------------------------------------------------

    def register(self, manifest: PluginManifest, handlers: dict[str, Callable] | None = None) -> None:
        if manifest.slug in self._plugins:
            raise ValueError(f"plugin {manifest.slug!r} is already registered")

        clashes = [c for c in manifest.commands if c in self._command_owner]
        if clashes:
            owners = {c: self._command_owner[c] for c in clashes}
            raise ValueError(f"command collision in {manifest.slug!r}: {owners}")

        handlers = handlers or {}
        missing = [c for c in manifest.commands if c not in handlers]
        if missing:
            raise ValueError(f"{manifest.slug!r} declares commands with no handler: {missing}")

        for command in manifest.commands:
            self._command_owner[command] = manifest.slug
        self._plugins[manifest.slug] = RegisteredPlugin(manifest=manifest, handlers=dict(handlers))

    # -- lifecycle ---------------------------------------------------------

    def enable(self, slug: str) -> None:
        self._plugin(slug).enabled = True

    def disable(self, slug: str) -> None:
        self._plugin(slug).enabled = False

    def is_enabled(self, slug: str) -> bool:
        return self._plugin(slug).enabled

    def _plugin(self, slug: str) -> RegisteredPlugin:
        try:
            return self._plugins[slug]
        except KeyError:
            raise KeyError(f"unknown plugin {slug!r}") from None

    # -- lookups -----------------------------------------------------------

    def manifests(self) -> list[PluginManifest]:
        return [p.manifest for p in self._plugins.values()]

    def enabled_plugins(self) -> Iterable[RegisteredPlugin]:
        return [p for p in self._plugins.values() if p.enabled]

    def handler_for(self, command: str) -> Callable | None:
        """Handler for *command*, or ``None`` when its plugin is disabled."""
        slug = self._command_owner.get(command)
        if slug is None:
            return None
        plugin = self._plugins[slug]
        if not plugin.enabled:
            return None
        return plugin.handlers.get(command)

    def commands_of(self, slug: str) -> dict[str, Callable]:
        """command → handler for one plugin, respecting enable state."""
        plugin = self._plugin(slug)
        return dict(plugin.handlers) if plugin.enabled else {}

    def active_commands(self) -> list[str]:
        """Commands that are actually live right now."""
        return sorted(
            command
            for command, slug in self._command_owner.items()
            if self._plugins[slug].enabled
        )
