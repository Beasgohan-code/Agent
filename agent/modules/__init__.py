"""Agent — feature modules.

Each module is a plugin: a manifest plus real command handlers. Registering a
module whose commands are declared but not implemented is impossible — the
registry rejects it.
"""

from . import encoder, linkshare

MODULES = (encoder, linkshare)

__all__ = ["MODULES", "encoder", "linkshare"]
