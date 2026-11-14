"""Agent — the services a module receives at registration time."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..health import HealthMonitor
from ..ui.theme import Theme
from ..utils.sender import ScreenSender
from .chats import ChatStore
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
    chats: ChatStore | None = None
    registry: object | None = None
    #: Callback prefix router, so a module can own a button without the UI layer
    #: knowing its data format.
    actions: object | None = None
    #: Voice-chat engine, present only when a session string and the libraries are.
    voice: object | None = None
    #: Who has premium, and what the tiers allow.
    premium: object | None = None
    events: object | None = None
    runtime: object | None = None
    lease: object | None = None
    logbook: object | None = None
    #: Running clones; set by the clone module when it is enabled.
    clones: object | None = None
    #: Builds the bot a clone runs; None means "the real AgentBot".
    clone_factory: object | None = None
    #: PostgreSQL, when DATABASE_URL is set; the stores prefer it over files.
    db: object | None = None
    plugin_access: object | None = None
    plugin_gate: object | None = None
    group_plugin_panel: object | None = None
    #: ``/start <payload>`` router: a module owns a prefix, not the UI layer.
    deeplinks: object | None = None

    @classmethod
    def build(
        cls,
        settings: Settings,
        theme: Theme,
        sender: ScreenSender,
        *,
        root: Path,
        db=None,
    ) -> "ModuleContext":
        return cls(
            settings=settings,
            theme=theme,
            sender=sender,
            jobs=JobQueue(concurrency=2),
            storage=Storage(root, db=db),
            links=LinkStore(root, settings.link_secret, default_ttl_hours=24, db=db),
            chats=ChatStore(root, db=db),
            db=db,
        )
