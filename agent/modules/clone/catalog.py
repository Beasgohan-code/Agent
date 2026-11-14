"""Reviewed guided templates; credential-bearing plugins stay unavailable."""

# action -> (registered module slug, presentation name, archive channel required)
TEMPLATES = {
    'files': ('filestore', 'FileStore', True),
    'encoder': ('encoder', 'Encoder', False),
    'moderation': ('moderation', 'Moderation', False),
    'postmaker': ('postmaker', 'Post maker', False),
    'linkshare': ('linkshare', 'Linkshare', False),
    'leech': ('leech', 'Leech', False),
    'ai_agent': ('ai_agent', 'AI Agent', False),
}
ALLOWED_PLUGINS = frozenset(item[0] for item in TEMPLATES.values())


def selection_label(slugs):
    names = {slug: name for slug, name, _ in TEMPLATES.values()}
    return ', '.join(names.get(slug, 'unsupported') for slug in slugs)
