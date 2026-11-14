"""Mandatory group protection survives settings and legacy disabled state."""
import json

import pytest

from agent.modules import select
from agent.platform.policy import GROUP_CORE, PROTECTED_PLUGINS
from agent.platform.runtime import PluginRuntime


@pytest.mark.parametrize('selection', [(), ('leech',), ('nonsense',), ('*',)])
def test_group_core_is_always_selected(selection):
    assert set(GROUP_CORE) <= {m.MANIFEST.slug for m in select(selection)}


@pytest.mark.parametrize('slug', PROTECTED_PLUGINS)
def test_core_cannot_be_disabled_even_with_custom_protection(slug):
    runtime = PluginRuntime(None, protected=())
    with pytest.raises(ValueError, match='cannot be disabled'):
        runtime.disable(slug)


def test_legacy_disabled_core_is_ignored_on_load_and_hydrate(tmp_path):
    path = tmp_path / 'runtime.json'
    path.write_text(json.dumps({'disabled': [*GROUP_CORE, 'music']}))
    runtime = PluginRuntime(None, state_path=path)
    for _ in range(2):
        assert all(not runtime.wants_disabled(slug) for slug in GROUP_CORE)
        assert runtime.wants_disabled('music')
        runtime.hydrate()
