"""Shared classification for the group-management core.

Availability is mandatory; individual protection rules remain configurable by
administrators. These modules never consume optional-plugin slots.
"""

GROUP_CORE = ("moderation", "group", "filters", "welcome", "reports", "security")
PROTECTED_PLUGINS = ("ops", "core", *GROUP_CORE)
OPTIONAL_SLOTS = 3

# Presentation priority, not a claim that every deployment has dependencies.
PRIMARY_FEATURES = ("encoder", "moderation", "postmaker", "music", "linkshare", "filestore", "leech", "ai_agent")
