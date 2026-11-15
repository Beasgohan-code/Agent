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


def plan_selection(requested):
    """Canonical reviewed set, including validation of mandatory core compatibility.

    Structural planning intentionally precedes credential collection. Full
    requirements are checked by validate_selection before commit and construction.
    Mandatory core is injected by AgentBot.select; don't store it as optional slots.
    """
    from dataclasses import replace
    from ...modules import MODULES
    from ...platform.policy import GROUP_CORE
    from ...platform.selection import resolve_selection
    manifests = [replace(m.MANIFEST, required_credentials=(), required_capabilities=(),
                         premium_required=False) for m in MODULES]
    requested = tuple(requested) if not isinstance(requested, str) else requested
    resolved = resolve_selection(requested, manifests=manifests, for_clone=True,
                                 mandatory=GROUP_CORE)
    explicit = {s.strip().lower() for s in requested}
    return tuple(s for s in resolved if s not in GROUP_CORE or s in explicit)


def validate_selection(requested, *, ai_api_key=None, ai_model=None,
                       assistant_session=None, capabilities=(), premium=False):
    from ...modules import MODULES
    from ...platform.credentials import validate_ai_key, validate_ai_model, CredentialError
    from ...platform.policy import GROUP_CORE
    from ...platform.selection import resolve_selection, SelectionError
    selection = plan_selection(requested)
    credentials = dict(ai_api_key=ai_api_key, ai_model=ai_model,
                       assistant_session=assistant_session)
    resolve_selection(selection, manifests=[m.MANIFEST for m in MODULES],
                      mandatory=GROUP_CORE, for_clone=True, credentials=credentials,
                      capabilities=capabilities, premium=premium)
    if 'ai_agent' in selection:
        try:
            validate_ai_key(ai_api_key)
            validate_ai_model(ai_model)
        except CredentialError as exc:
            raise SelectionError('invalid_credentials', plugin='ai_agent', fields=(exc.field,)) from None
    if 'music' in selection:
        from .assistant import validate_session
        try:
            validate_session(assistant_session)
        except Exception:
            raise SelectionError('invalid_credentials', plugin='music', fields=('assistant_session',)) from None
    return selection
