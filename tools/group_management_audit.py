"""Summarize the reviewed feature inventory without claiming behavioral parity.

Run from the checkout: .venv/bin/python tools/group_management_audit.py
Produces JSON on stdout; no network, credentials, migrations or reference code.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def summarize(review, command_owners):
    counts = Counter(feature["assessment"] for feature in review["features"])
    return {
        "reviewed_on": review["reviewed_on"],
        "documentation_pages_reviewed": len(
            {url for feature in review["features"] for url in feature["sources"]}
        ),
        "feature_groups": len(review["features"]),
        "assessments": dict(sorted(counts.items())),
        "all_features_implemented": False,
        "limitation": "Registered command names are declarations, not proof of runtime availability, persistence or semantic equivalence.",
        "declared_command_checks": [
            {
                "feature": feature["feature"],
                "command": name,
                "registered_owner": command_owners.get(name),
            }
            for feature in review["features"]
            for name in feature["implemented_commands"]
        ],
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from agent.modules import MODULES

    owners = {
        name: module.MANIFEST.slug
        for module in MODULES
        for name in module.MANIFEST.commands
    }
    review = json.loads((root / "docs/group_management_review.json").read_text())
    print(json.dumps(summarize(review, owners), indent=2))
