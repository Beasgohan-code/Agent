"""New source intake stays inert and captures dynamic-command clues safely."""

import importlib
import json
from pathlib import Path


def scanner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    return importlib.import_module("feature_source_catalog")


def test_python_command_dictionary_does_not_execute_source(tmp_path, monkeypatch):
    module = scanner(monkeypatch)
    marker = tmp_path / "executed"
    source = tmp_path / "commands.py"
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass BotCommands:\n    _static_commands = {{'Play': ['play','p'], 'Cancel': 'cancel'}}\n"
    )
    names, flags = module.candidates(source)
    assert names == {"play", "p", "cancel"}
    assert flags == [] and not marker.exists()


def test_typescript_command_aliases_are_candidates_only(tmp_path, monkeypatch):
    module = scanner(monkeypatch)
    source = tmp_path / "commands" / "play.ts"
    source.parent.mkdir()
    source.write_text(
        "export default defineCommand({name: 'play', aliases: ['p','song'], handler: run})"
    )
    assert module.candidates(source)[0] == {"play", "p", "song"}


def test_manifest_pins_all_requested_folders_without_importing_them():
    root = Path(__file__).resolve().parents[1]
    sources = json.loads((root / "docs/feature_sources.json").read_text())
    assert {source["path"] for source in sources} == {
        "music/Videl0",
        "music/Playeon",
        "saver",
        "Encoder",
        "Filestore",
        "Linkshare",
        "leech",
    }
    for source in sources:
        assert len(source["revision"]) == 40
        assert source["url"].startswith("https://github.com/")
        assert source["license_review"]
        folder = source["path"].split("/")[0]
        assert "/" + folder + "/" in (root / ".gitignore").read_text()
        assert folder + "/" in (root / ".dockerignore").read_text()


def test_consolidated_review_covers_all_sources_without_claiming_integration():
    root = Path(__file__).resolve().parents[1]
    review = json.loads((root / "docs/repository_review.json").read_text())
    sources = json.loads((root / "docs/feature_sources.json").read_text())
    rows = review["repositories"]
    assert len(rows) == len({row["url"].casefold() for row in rows}) == 35
    assert sum("historical_29_repository_index" in row["intake"] for row in rows) == 29
    assert {
        row["url"] for row in rows if "explicit_feature_source" in row["intake"]
    } == {source["url"] for source in sources}
    assert review["all_features_implemented"] is False
    assert review["runtime_code_imported"] is False
    assert review["source_execution_performed"] is False
    for row in rows:
        assert row["url"].startswith("https://github.com/")
        assert len(row["reference_revision"]) == 40
        assert row["license_review"]
        assert row["integration_status"] == "reference_only_not_semantic_parity"
        assert row["root_tree_review"]["status"] in ("retrieved", "unavailable")
        assert row["root_tree_review"]["limitation"]


def test_reference_review_folders_cover_the_pinned_sources_without_runtime_imports():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "docs/feature_sources.json").read_text())
    status = json.loads((root / "docs/reference_checkout_status.json").read_text())
    rows = {row["path"]: row for row in status["checkouts"]}
    assert status["runtime_imported"] is False
    assert set(rows) == {source["path"] for source in manifest}
    for source in manifest:
        row = rows[source["path"]]
        assert row["status"] == "review_clone_prepared"
        assert row["pinned_materialized_revision"] == source["revision"]
        assert row["executed"] is False
        assert row["text_files_materialized"] > 0
        assert "credential" in row["limit"]
