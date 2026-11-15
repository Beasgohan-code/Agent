"""Retired names must not leak back into handlers, menus or help."""
from agent.modules import MODULES
from agent.modules import encoder, filestore, leech, postmaker, ops, renamer
from agent.modules.music import playlists
from agent.platform.menu import DESCRIPTIONS, GROUP_ONLY
from agent.ui.screens import HELP_SECTIONS
from test_plugins import make_ctx

RETIRED = {'delcaption', 'enccancel', 'encinfo', 'encpreset', 'fsave', 'leechstats',
           'playlistinfo', 'postpreview', 'posttemplate', 'storequota', 'storestats',
           'taskbackend', 'tasklist', 'taskstatus', 'unsetlog'}


def test_retired_commands_absent_from_all_declarations_and_public_metadata():
    declared = {name for module in MODULES for name in module.MANIFEST.commands}
    assert not RETIRED & declared
    assert not RETIRED & DESCRIPTIONS.keys()
    assert not RETIRED & GROUP_ONLY
    help_names = {name for _, _, names in HELP_SECTIONS for name in names}
    assert not RETIRED & help_names
    assert 'mediainfo' in encoder.MANIFEST.commands
    assert 'playlistinfo' not in playlists.COMMANDS


def test_retired_handlers_are_not_registered_and_storage_is_preserved(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.chats.put(-100, 'post_template', 'existing layout')
    for module in (encoder, filestore, leech, postmaker, ops, renamer):
        _, handlers = module.build(ctx)
        assert not RETIRED & handlers.keys()
    assert ctx.chats.get(-100, 'post_template') == 'existing layout'
