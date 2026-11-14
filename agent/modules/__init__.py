"""Agent — feature modules.

Every module is compiled in; which ones *register* is the deployment's choice
(``PLUGINS``, default: :data:`agent.config.DEFAULT_PLUGINS`). That distinction is
the whole lifecycle rule of this bot: a module that is not selected registers
nothing — no commands, no watchers, no menu entries — so it cannot half-work.

:data:`SHELL` is the exception, and it is not a plugin: ``ops`` owns
``/plugins``, ``/plugin`` and ``/restart``, and ``core`` owns ``/menu``,
``/about``, ``/status``, ``/cancel`` and ``/owner``. A build that dropped those
would accept files and offer no way to look at, cancel or repair itself, so
they register whatever ``PLUGINS`` says.

Order matters only for collisions: the registry rejects any command declared
twice, so adding a module can never silently shadow another.
"""

from . import (
    clone,
    core,
    encoder,
    filestore,
    filters,
    group,
    leech,
    linkshare,
    moderation,
    music,
    ops,
    postmaker,
    premium,
    renamer,
    reports,
    security,
    utilities,
    welcome,
)

#: Registration order. The selection keeps this order, so a build with a subset
#: behaves exactly like the full build with the others switched off.
ORDER = (
    "ops",
    "core",
    "clone",
    "encoder",
    "filestore",
    "filters",
    "group",
    "leech",
    "linkshare",
    "moderation",
    "music",
    "postmaker",
    "premium",
    "renamer",
    "reports",
    "security",
    "utilities",
    "welcome",
)

#: Modules that are part of the bot itself rather than a feature: the controls
#: and the front door. Always registered, never switchable off from the panel.
SHELL = ("ops", "core")

ALL_MODULES = {
    "ops": ops,
    "core": core,
    "clone": clone,
    "encoder": encoder,
    "filestore": filestore,
    "filters": filters,
    "group": group,
    "leech": leech,
    "linkshare": linkshare,
    "moderation": moderation,
    "music": music,
    "postmaker": postmaker,
    "premium": premium,
    "renamer": renamer,
    "reports": reports,
    "security": security,
    "utilities": utilities,
    "welcome": welcome,
}


def select(slugs) -> tuple:
    """The modules to register for *slugs*, in :data:`ORDER`.

        ``("*",)`` selects everything compiled in. Otherwise *slugs* plus
        :data:`SHELL`. Unknown slugs are returned in :func:`unknown` rather than
        raising, so a typo in ``PLUGINS`` costs one plugin and a log line, not the
        whole bot.
        
    """
    requested = tuple(slugs or ())
    if requested == ("*",):
        return tuple(ALL_MODULES[name] for name in ORDER)
    wanted = set(requested) | set(SHELL)
    return tuple(ALL_MODULES[name] for name in ORDER if name in wanted)


def unknown(slugs) -> tuple[str, ...]:
    """Slugs in *slugs* that this build has no module for."""
    requested = tuple(slugs or ())
    if requested == ("*",):
        return ()
    return tuple(name for name in requested if name not in ALL_MODULES)


def not_selected(slugs) -> tuple[str, ...]:
    """Modules compiled in but not registering, in :data:`ORDER`."""
    chosen = {module.MANIFEST.slug for module in select(slugs)}
    return tuple(name for name in ORDER if name not in chosen)


#: Everything compiled in, for tests and for ``/plugins``-style introspection.
MODULES = tuple(ALL_MODULES[name] for name in ORDER)
