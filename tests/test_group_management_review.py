"""Reviewed documentation is an honest gap inventory, not command-name parity."""

import json
from pathlib import Path
from agent.modules import MODULES

ROOT = Path(__file__).resolve().parents[1]


def test_review_inventory_covers_documentation_and_points_to_real_evidence():
    review = json.loads((ROOT / "docs/group_management_review.json").read_text())
    assert review["all_features_implemented"] is False
    sources = [url for feature in review["features"] for url in feature["sources"]]
    assert len(sources) == len(set(sources)) == 50
    assert all(url.startswith("https://missrose.org/docs/") for url in sources)
    commands = {name for module in MODULES for name in module.MANIFEST.commands}
    for feature in review["features"]:
        assert feature["source_text_reviewed"] is True
        assert feature["assessment"] in (
            "partial",
            "not_implemented",
            "reference_only",
            "implemented_with_differences",
        )
        assert feature["differences_and_remaining"]
        assert set(feature["implemented_commands"]) <= commands
        assert all(
            (ROOT / path).is_file() for path in feature["code"] + feature["tests"]
        )


def test_audit_summary_does_not_turn_registration_into_parity():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "group_audit", ROOT / "tools/group_management_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    review = json.loads((ROOT / "docs/group_management_review.json").read_text())
    summary = module.summarize(review, {})
    assert summary["documentation_pages_reviewed"] == 50
    assert summary["all_features_implemented"] is False
    assert all(
        row["registered_owner"] is None for row in summary["declared_command_checks"]
    )
    assert "not proof" in summary["limitation"]
