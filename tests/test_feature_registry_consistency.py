"""Feature additions must not introduce duplicate command declarations."""
from agent.modules import MODULES
from agent.platform.menu import DESCRIPTIONS


def test_every_manifest_command_is_unique_and_has_help():
    names = {}
    for module in MODULES:
        manifest = module.MANIFEST
        assert len(manifest.commands) == len(set(manifest.commands)), manifest.slug
        for command in manifest.commands:
            assert command not in names, (command,names.get(command),manifest.slug)
            names[command] = manifest.slug
            assert command in DESCRIPTIONS, command
