"""Reviewed guided templates; credential-bearing templates require their own setup."""

# action -> (registered module slug, presentation name, archive channel required)
TEMPLATES = {
    "files": ("filestore", "FileStore", True),
    "encoder": ("encoder", "Encoder", False),
    "moderation": ("moderation", "Group Management", False),
    "postmaker": ("postmaker", "Post maker", False),
    "linkshare": ("linkshare", "Linkshare", False),
    "leech": ("leech", "Leech", False),
    "music": ("music", "Music", False),
    "ai_agent": ("ai_agent", "AI Agent", False),
}
ALLOWED_PLUGINS = frozenset(item[0] for item in TEMPLATES.values())


def selection_label(slugs):
    names = {
        slug: name
        for action, (slug, name, _) in TEMPLATES.items()
        if action not in ("file_suite", "full_suite")
    }
    return ", ".join(names.get(slug, "unsupported") for slug in slugs)


# Bundles are explicit, reviewed plugin sets, not arbitrary plugin imports.
FILE_SUITE = ("filestore", "encoder", "linkshare", "leech", "postmaker")
TEMPLATES["file_suite"] = ("filestore", "File tools suite", True)
FULL_SUITE = FILE_SUITE + ("moderation", "music", "ai_agent")
TEMPLATES["full_suite"] = ("filestore", "Full Meiko suite", True)
TEMPLATE_PLUGINS = {
    action: (FULL_SUITE if action == "full_suite" else FILE_SUITE if action == "file_suite" else (slug,))
    for action, (slug, _name, _archive) in TEMPLATES.items()
}
SUPPORTED_SELECTIONS = frozenset(TEMPLATE_PLUGINS.values())
