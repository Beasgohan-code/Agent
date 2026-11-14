"""Agent — feature modules.

Order matters only for collisions: the registry rejects any command declared
twice, so adding a module can never silently shadow another.
"""

from . import (
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
    renamer,
    reports,
    security,
    utilities,
    welcome,
)

MODULES = (
    ops,
    core,
    encoder,
    filestore,
    filters,
    group,
    leech,
    linkshare,
    moderation,
    music,
    postmaker,
    renamer,
    reports,
    security,
    utilities,
    welcome,
)
