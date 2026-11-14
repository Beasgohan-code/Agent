"""New source intake stays inert and captures dynamic-command clues safely."""
import importlib
import json
from pathlib import Path


def scanner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'tools'))
    return importlib.import_module('feature_source_catalog')


def test_python_command_dictionary_does_not_execute_source(tmp_path, monkeypatch):
    module = scanner(monkeypatch)
    marker = tmp_path / 'executed'
    source = tmp_path / 'commands.py'
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass BotCommands:\n    _static_commands = {{'Play': ['play','p'], 'Cancel': 'cancel'}}\n")
    names, flags = module.candidates(source)
    assert names == {'play', 'p', 'cancel'}
    assert flags == [] and not marker.exists()


def test_typescript_command_aliases_are_candidates_only(tmp_path, monkeypatch):
    module = scanner(monkeypatch)
    source = tmp_path / 'commands' / 'play.ts'
    source.parent.mkdir()
    source.write_text("export default defineCommand({name: 'play', aliases: ['p','song'], handler: run})")
    assert module.candidates(source)[0] == {'play', 'p', 'song'}


def test_manifest_pins_all_requested_folders_without_importing_them():
    root = Path(__file__).resolve().parents[1]
    sources = json.loads((root / 'docs/feature_sources.json').read_text())
    assert {source['path'] for source in sources} == {'music/Videl0', 'music/Playeon', 'saver', 'Encoder', 'Filestore', 'Linkshare', 'leech'}
    for source in sources:
        assert len(source['revision']) == 40
        assert source['url'].startswith('https://github.com/')
        assert source['license_review']
        folder = source['path'].split('/')[0]
        assert '/' + folder + '/' in (root / '.gitignore').read_text()
        assert folder + '/' in (root / '.dockerignore').read_text()
