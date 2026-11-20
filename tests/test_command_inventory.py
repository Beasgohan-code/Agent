"""Inventory comes from source manifests, includes aliases and states real gaps."""
from tools.command_inventory import inventory,render


def test_inventory_covers_all_declared_commands_and_shell_aliases():
    from agent.modules import MODULES
    names=[row[0] for row in inventory()]
    assert len(names)==len(set(names))
    assert {'start','restart_bot','help','h','ping'}<=set(names)
    for module in MODULES:
        assert set(module.MANIFEST.commands)<=set(names)
    text=render()
    assert 'not proof of live' in text
    assert '/tpromote' in text and '/tagall' in text and '/etagall' in text
    assert 'not full feature parity' in text
    assert 'One-tap Unban control remains' in text
