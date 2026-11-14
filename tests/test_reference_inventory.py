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


def test_multi_repository_index_reports_actual_scope_and_non_python_files(tmp_path, monkeypatch):
    root = tmp_path / 'refs'
    repo = root / 'example'
    (repo / '.git').mkdir(parents=True)
    (repo / 'plugin.py').write_text("@filters.command('hello')\ndef handler(): pass\n")
    (repo / 'ui.ts').write_text('export const ui = true;\n')
    def output(command, **kwargs):
        if 'ls-files' in command:
            return b'plugin.py\0ui.ts\0'
        return 'a' * 40 + '\n'
    monkeypatch.setattr(module.subprocess, 'check_output', output)
    destination = tmp_path / 'report'
    module.inventory_all(root, destination)
    summary = (destination / 'README.md').read_text()
    assert 'Scope: 1 reference checkouts' in summary
    assert 'Total tracked files: **2**' in summary
    assert '.ts: 1' in summary
    assert 'hello' in (destination / 'example.md').read_text()
