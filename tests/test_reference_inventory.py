"""Static reference review must never import untrusted modules."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('reference_inventory', Path(__file__).resolve().parents[1] / 'tools' / 'reference_inventory.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_static_scan_records_commands_and_risks_without_execution(tmp_path):
    source = tmp_path / 'reference.py'
    marker = tmp_path / 'executed'
    source.write_text(f'''from pathlib import Path
Path({str(marker)!r}).touch()
@filters.command(['hello', 'help'])
def handler():
    eval('untrusted')
''')
    digest, commands, flags = module.inspect_file(source)
    assert len(digest) == 12
    assert commands == ['hello', 'help']
    assert flags == ['eval:5']
    assert not marker.exists()


def test_invalid_reference_is_reported_not_silently_omitted(tmp_path):
    source = tmp_path / 'invalid.py'
    source.write_text('def broken(:\n')
    _, commands, flags = module.inspect_file(source)
    assert commands == []
    assert flags == ['parse:SyntaxError line 1']
