"""Agent — feature modules.

Order matters only for collisions: the registry rejects any command declared
twice, so adding a module can never silently shadow another.
"""

from . import core, encoder, filters, linkshare, moderation, ops, utilities, welcome

MODULES = (ops, core, encoder, filters, linkshare, moderation, utilities, welcome)
