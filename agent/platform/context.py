"""Agent — the services a module receives at registration time."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..health import HealthMonitor
from ..ui.theme import Theme
from ..utils.sender import ScreenSender
from .jobs import JobQueue
from .links import LinkStore
from .storage import Storage


@dataclass
class ModuleContext:
    """Shared infrastructure handed to every module.

    Modules never build their own queue, storage or link signer — that is the
    whole point of the shared layer.
    """

    settings: Settings
    theme: Theme
    sender: ScreenSender
    jobs: JobQueue
    storage: Storage
    links: LinkStore
    monitor: HealthMonitor | None = None
    client: object | None = None

    @classmethod
    def build(cls, settings: Settings, theme: Theme, sender: ScreenSender, *, root: Path) -> "ModuleContext":
        return cls(
            settings=settings,
            theme=theme,
            sender=sender,
            jobs=JobQueue(concurrency=2),
            storage=Storage(root),
            links=LinkStore(root, settings.link_secret, default_ttl_hours=24),
        )
