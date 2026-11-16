"""Shared classification for the group-management core.

Availability is mandatory; individual protection rules remain configurable by
administrators. These modules never consume optional-plugin slots.
"""

GROUP_CORE = ("moderation", "group", "filters", "welcome", "reports", "security", "federations")
PROTECTED_PLUGINS = ("ops", "core", *GROUP_CORE)
OPTIONAL_SLOTS = 3

# Presentation priority, not a claim that every deployment has dependencies.
PRIMARY_FEATURES = ("encoder", "moderation", "postmaker", "music", "linkshare", "filestore", "leech", "ai_agent")


def is_worker(settings):
    """Worker settings are assigned by CloneManager with a clone tenant scope."""
    return (getattr(settings, 'db_scope', None) or '').startswith('clone:')


def worker_job_tools(plugins):
    """Expose job navigation only for workers with file-producing job modules."""
    return '*' in plugins or bool({'encoder', 'leech', 'renamer'} & set(plugins))
