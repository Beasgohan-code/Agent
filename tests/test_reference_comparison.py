"""Reference comparison must remain non-executing and uncertainty-aware."""
import importlib
from pathlib import Path


def test_command_comparison_distinguishes_evidence_without_running_refs(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'tools'))
    module = importlib.import_module('compare_reference_commands')
    repo = tmp_path / 'refs' / 'example'
    (repo / '.git').mkdir(parents=True)
    marker = tmp_path / 'executed'
    (repo / 'handler.py').write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n@filters.command('known')\ndef handler(): pass\n")
    (repo / 'menu.ts').write_text("const clue = 'dynamic';")
    (repo / 'bad.py').write_text('def broken(:\n')
    report = module.compare(repo.parent, [('known', 'test'), ('dynamic', 'test'), ('missing', 'test')])
    assert '`/known` | test | literal candidate' in report
    assert '`/dynamic` | test | source-text clue only' in report
    assert '`/missing` | test | no static match' in report
    assert 'bad.py: parse:SyntaxError' in report
    assert not marker.exists()
