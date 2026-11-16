"""Red acceptance contracts for the proposed first catalogue slice.

These intentionally expose current limitations. Do not xfail/skip them or weaken
assertions. No runtime implementation accompanies this audit. Proposed pure API:
manifest.resolve_selection(selected, manifests=...) -> ordered tuple of slugs;
ValueError for unknown, conflicting or cyclic selections. It must not import code.
"""
from dataclasses import replace

import pytest

from agent.platform import manifest
from agent.modules.clone.manager import CloneError
from agent.modules.clone.store import Clone
from test_clone import build, TOKEN_A, MEMBER


def resolver():
    resolve = getattr(manifest, 'resolve_selection', None)
    assert callable(resolve), 'Missing pure plugin dependency/conflict resolver'
    return resolve


def test_arbitrary_compatible_clone_selection_reaches_existing_worker_settings(tmp_path):
    ctx, _, _ = build(tmp_path)
    clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
                  profile='tiny', selected_plugins=('encoder', 'postmaker'))
    settings = ctx.clones.settings_for(clone)
    assert set(settings.plugins) == {'encoder', 'postmaker'}
    assert settings.db_scope == 'clone:111111111'
    assert settings.bot_token == TOKEN_A


def test_dependency_resolution_computes_stable_deduplicated_closure():
    resolve = resolver()
    base = manifest.PluginManifest(slug='base', name='Base', version='1.0.0', description='test')
    child = replace(base, slug='child', dependencies=('base',))
    assert resolve(('child', 'child'), manifests=(child, base)) == ('base', 'child')
    with pytest.raises(ValueError, match='(?i)unknown|unavailable|missing'):
        resolve(('child',), manifests=(child,))


def test_conflict_rejection_is_symmetric_even_if_declared_on_only_one_plugin():
    resolve = resolver()
    a = manifest.PluginManifest(slug='a', name='A', version='1.0.0', description='test')
    b = replace(a, slug='b', conflicts=('a',))
    for selection in (('a', 'b'), ('b', 'a')):
        with pytest.raises(ValueError, match='(?i)conflict'):
            resolve(selection, manifests=(a, b))


@pytest.mark.parametrize('key,model', [
    ('not-a-provider-key', 'model'),
    ('sk-' + 'a' * 20, 'invalid model with spaces'),
    ('   ', 'model'),
])
def test_persisted_invalid_ai_credentials_are_rejected_before_worker_build(tmp_path, key, model):
    ctx, _, _ = build(tmp_path)
    clone = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
                  selected_plugins=('ai_agent',), ai_api_key=key, ai_model=model)
    with pytest.raises(CloneError):
        ctx.clones.settings_for(clone)
