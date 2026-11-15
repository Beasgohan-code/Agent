"""Pure plugin catalogue validation and deterministic selection planning.

No module discovery, imports of plugin implementations, IO, entitlement lookups,
or activation: callers provide observed credentials/capabilities and authority.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

SLUG = re.compile(r'[a-z][a-z0-9_]{0,63}')


class SelectionError(ValueError):
    """Safe structured failure. Never retains input credentials or their values."""
    def __init__(self, code, *, plugin=None, fields=()):
        self.code, self.plugin, self.fields = code, plugin, tuple(fields)
        super().__init__(code.replace('_', ' ') + (f': {plugin}' if plugin else '') +
                         (f' ({", ".join(self.fields)})' if self.fields else ''))

    def as_dict(self):
        return {'code': self.code, 'plugin': self.plugin, 'fields': list(self.fields)}


def _slugs(values):
    if isinstance(values, str):
        raise SelectionError('invalid_selection')
    try:
        result = set()
        for value in values:
            if not isinstance(value, str) or not SLUG.fullmatch(value.strip().lower()):
                raise SelectionError('invalid_selection')
            result.add(value.strip().lower())
        return tuple(sorted(result))
    except TypeError:
        raise SelectionError('invalid_selection') from None


def catalogue(manifests):
    """Validate all declarations, even those outside the requested selection."""
    from .manifest import PluginManifest
    result = {}
    for item in manifests:
        if not isinstance(item, PluginManifest):
            raise SelectionError('invalid_manifest')
        if any(not isinstance(getattr(item, field), str) or not getattr(item, field).strip()
               for field in ('name', 'version', 'description')):
            raise SelectionError('invalid_manifest')
        if not isinstance(item.slug, str) or not SLUG.fullmatch(item.slug):
            raise SelectionError('invalid_manifest')
        if item.slug in result:
            raise SelectionError('duplicate_slug', plugin=item.slug)
        for field in ('dependencies', 'conflicts', 'required_credentials', 'required_capabilities'):
            values = getattr(item, field)
            if (not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip()
                    or v != v.strip() for v in values) or len(set(values)) != len(values)):
                raise SelectionError('invalid_manifest', plugin=item.slug, fields=(field,))
        for field in ('clone_compatible', 'group_compatible', 'premium_required', 'default_enabled'):
            if type(getattr(item, field)) is not bool:
                raise SelectionError('invalid_manifest', plugin=item.slug, fields=(field,))
        if (not isinstance(item.resource_requirements, dict) or any(
                not isinstance(k, str) or not k or type(v) is not int or v < 0
                for k, v in item.resource_requirements.items())):
            raise SelectionError('invalid_manifest', plugin=item.slug, fields=('resource_requirements',))
        if set(item.dependencies) & set(item.conflicts) or item.slug in item.conflicts:
            raise SelectionError('invalid_manifest', plugin=item.slug)
        result[item.slug] = item
    for item in result.values():
        for dependency in item.dependencies:
            if dependency not in result:
                raise SelectionError('unknown_dependency', plugin=item.slug)
        for conflict in item.conflicts:
            if conflict not in result:
                raise SelectionError('unknown_conflict', plugin=item.slug)
    # Validate cycles throughout the catalogue, not only reachable requests.
    _ordered(result, tuple(sorted(result)))
    return result


def _ordered(items, requested):
    visiting, visited, ordered = set(), set(), []

    def visit(slug):
        if slug in visiting:
            raise SelectionError('dependency_cycle', plugin=slug)
        if slug in visited:
            return
        if slug not in items:
            raise SelectionError('unknown_plugin', plugin=slug)
        visiting.add(slug)
        for dependency in sorted(items[slug].dependencies):
            visit(dependency)
        visiting.remove(slug)
        visited.add(slug)
        ordered.append(slug)

    for slug in sorted(requested):
        visit(slug)
    return tuple(ordered)


def resolve_selection(selected, *, manifests, for_clone=False, for_group=False,
                      mandatory=(), credentials=None, capabilities=(), premium=False):
    items = catalogue(manifests)
    ordered = _ordered(items, _slugs(selected) + _slugs(mandatory))
    credentials = credentials if isinstance(credentials, Mapping) else {}
    if isinstance(capabilities, str):
        raise SelectionError('invalid_capabilities')
    try:
        capabilities = set(capabilities)
        if any(not isinstance(value, str) or not value.strip() for value in capabilities):
            raise SelectionError('invalid_capabilities')
    except TypeError:
        raise SelectionError('invalid_capabilities') from None
    for slug in ordered:
        item = items[slug]
        if for_clone and not item.clone_compatible:
            raise SelectionError('clone_incompatible', plugin=slug)
        if for_group and not item.group_compatible:
            raise SelectionError('group_incompatible', plugin=slug)
        if set(item.conflicts) & set(ordered):
            raise SelectionError('plugin_conflict', plugin=slug)
        missing = [key for key in item.required_credentials
                   if not isinstance(credentials.get(key), str) or not credentials[key].strip()]
        if missing:
            raise SelectionError('missing_credentials', plugin=slug, fields=missing)
        from .credentials import validate_ai_key, validate_ai_model, CredentialError
        validators = {'ai_api_key': validate_ai_key, 'ai_model': validate_ai_model}
        for key in item.required_credentials:
            if key in validators:
                try:
                    validators[key](credentials[key])
                except CredentialError:
                    raise SelectionError('invalid_credentials', plugin=slug, fields=(key,)) from None
        missing = sorted(set(item.required_capabilities) - capabilities)
        if missing:
            raise SelectionError('missing_capabilities', plugin=slug, fields=missing)
        if item.premium_required and premium is not True:
            raise SelectionError('premium_required', plugin=slug)
    return ordered
