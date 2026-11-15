"""Pure catalogue contracts; no clients, workers, storage or provider calls."""
from dataclasses import replace
import pytest
from agent.platform.manifest import PluginManifest
from agent.platform import selection


def plugin(slug, **kwargs):
    return PluginManifest(slug=slug, name=slug, version='1.0.0', description='test', **kwargs)


def test_transitive_normalized_order_and_duplicates():
    catalogue = [plugin('a'), plugin('b', dependencies=('a',)), plugin('c', dependencies=('b',))]
    assert selection.resolve_selection((' C ', 'a', 'C'), manifests=catalogue) == ('a', 'b', 'c')


@pytest.mark.parametrize('catalogue,code', [
    ([plugin('a'), plugin('a')], 'duplicate_slug'),
    ([plugin('a', dependencies=('missing',))], 'unknown_dependency'),
    ([plugin('a', dependencies=('b',)), plugin('b', dependencies=('a',))], 'dependency_cycle'),
    ([plugin('a', dependencies=('b',), conflicts=('b',)), plugin('b')], 'invalid_manifest'),
])
def test_invalid_catalogue(catalogue, code):
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=catalogue)
    assert error.value.code == code


def test_unknown_and_symmetric_conflict():
    catalogue = [plugin('a'), plugin('b', conflicts=('a',))]
    for slugs in [('b', 'a'), ('a', 'b')]:
        with pytest.raises(selection.SelectionError, match='conflict'):
            selection.resolve_selection(slugs, manifests=catalogue)
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('unknown',), manifests=catalogue)
    assert error.value.code == 'unknown_plugin'


def test_clone_compatibility_is_optin_and_group_core_mandatory():
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=[plugin('a')], for_clone=True)
    assert error.value.code == 'clone_incompatible'
    catalogue = [plugin('a', clone_compatible=True), plugin('moderation', clone_compatible=True)]
    assert selection.resolve_selection(('a',), manifests=catalogue, for_clone=True,
                                       mandatory=('moderation',)) == ('a', 'moderation')


def test_requirements_and_premium_are_explicit_and_secret_safe():
    p = plugin('a', clone_compatible=True, required_credentials=('key',),
               required_capabilities=('network',), premium_required=True)
    kwargs = dict(manifests=[p], for_clone=True)
    for extras, code in [({}, 'missing_credentials'),
                         ({'credentials': {'key': 'SECRET'}}, 'missing_capabilities'),
                         ({'credentials': {'key': 'SECRET'}, 'capabilities': {'network'}}, 'premium_required')]:
        with pytest.raises(selection.SelectionError) as error:
            selection.resolve_selection(('a',), **kwargs, **extras)
        assert error.value.code == code
        assert 'SECRET' not in str(error.value)
    assert selection.resolve_selection(('a',), **kwargs, credentials={'key': 'SECRET'},
                                       capabilities={'network'}, premium=True) == ('a',)


def test_permutations_have_same_dependency_order():
    from itertools import permutations
    catalogue = [plugin('a'), plugin('b', dependencies=('a',)), plugin('c')]
    results = {selection.resolve_selection(order, manifests=catalogue) for order in permutations(('b', 'c', 'a'))}
    assert results == {('a', 'b', 'c')}


def test_unknown_conflicts_and_malformed_declarations_rejected():
    with pytest.raises(selection.SelectionError):
        selection.resolve_selection(('a',), manifests=[plugin('a', conflicts=('missing',))])
    for bad in [replace(plugin('a'), slug='A!'), plugin('a', dependencies='oops'),
                plugin('a', clone_compatible='yes'), plugin('a', resource_requirements={'memory_mb': -1})]:
        with pytest.raises(selection.SelectionError):
            selection.resolve_selection(('a',), manifests=[bad])


def test_group_compatibility_requires_declaration_and_bad_credentials_are_structured():
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=[plugin('a')], for_group=True)
    assert error.value.code == 'group_incompatible'
    p = plugin('a', required_credentials=('ai_api_key',))
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=[p], credentials={'ai_api_key': 'secret-not-valid'})
    assert error.value.as_dict() == {'code': 'invalid_credentials', 'plugin': 'a', 'fields': ['ai_api_key']}
    assert 'secret-not-valid' not in str(error.value)


def test_default_enabled_false_does_not_register_live_handlers():
    from agent.platform.manifest import PluginRegistry
    registry = PluginRegistry()
    registry.register(plugin('a', commands=('hello',), default_enabled=False), {'hello': lambda: None})
    assert not registry.is_enabled('a')
    assert registry.handler_for('hello') is None


def test_dependency_conflicting_with_mandatory_core_is_rejected():
    catalogue = [plugin('moderation', clone_compatible=True),
                 plugin('a', clone_compatible=True, conflicts=('moderation',))]
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=catalogue, for_clone=True, mandatory=('moderation',))
    assert error.value.code == 'plugin_conflict'


@pytest.mark.parametrize('bad', [None, 7, {'a': True}, b'a'])
def test_malformed_request_shapes_raise_structured_errors(bad):
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(bad, manifests=[plugin('a')])
    assert error.value.code == 'invalid_selection'


@pytest.mark.parametrize('bad', [None, 7, {'a': 'not-a-manifest'}])
def test_malformed_catalogue_shapes_raise_structured_errors(bad):
    with pytest.raises(selection.SelectionError) as error:
        selection.resolve_selection(('a',), manifests=bad)
    assert error.value.code == 'invalid_catalogue'
