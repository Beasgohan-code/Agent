"""Retire the vault inspector without removing stored data or delivery."""
import pytest
from agent.modules import filestore
from agent.ui.workers import commands
from test_filestore_clone_frontdoor import ctx


@pytest.mark.parametrize('scope,plugins', [
    ('main', ('filestore',)),
    ('clone:111111111', ('filestore',)),
    ('clone:111111111', ('filestore', 'linkshare')),
])
def test_no_check_registration_or_worker_help(scope, plugins):
    manifest, handlers = filestore.build(ctx(scope=scope, plugins=plugins))
    assert 'check' not in manifest.commands
    assert 'check' not in handlers
    assert 'check' not in commands('filestore', set(handlers))
    assert 'batch' in handlers and 'custom_batch' in handlers
    assert set(manifest.commands) == set(handlers)


def test_specialized_clone_only_exposes_archive_creation_commands():
    manifest, handlers = filestore.build(ctx())
    assert set(handlers) == {'genlink', 'batch', 'custom_batch'}
