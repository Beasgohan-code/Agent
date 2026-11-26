"""Validate the saved UI patch without importing or executing upstream code."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def structure(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = "TEXT"
    return ast.dump(tree)


def interfaces(source):
    """Commands, callbacks, URLs and callback parameter IDs are not UI labels."""
    tree = ast.parse(source)
    values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("command", "regex"):
            values.append(ast.dump(copy.deepcopy(node)))
        for keyword in node.keywords:
            if keyword.arg in ("callback_data", "url"):
                values.append(ast.dump(copy.deepcopy(keyword)))
    return values


def validate(root):
    root = Path(root).resolve()
    folder = root / "patches/filestore"
    manifest = json.loads((folder / "manifest.json").read_text())
    checkout = root / manifest["edited_checkout"]
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        for record in manifest["files"]:
            relative = record["path"]
            original = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "show",
                    f"{manifest['revision']}:{relative}",
                ],
                text=True,
            )
            edited = (checkout / relative).read_text()
            assert (
                hashlib.sha256(original.encode()).hexdigest() == record["before_sha256"]
            )
            assert hashlib.sha256(edited.encode()).hexdigest() == record["after_sha256"]
            assert structure(original) == structure(edited), (
                "Executable structure changed"
            )
            assert interfaces(original) == interfaces(edited), (
                "Command/callback interface changed"
            )
            if record.get("literal_changes"):
                original_tree, edited_tree = ast.parse(original), ast.parse(edited)
                changes = {
                    item["before"]: item["after"] for item in record["literal_changes"]
                }
                for node in ast.walk(original_tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        node.value = changes.get(node.value, node.value)
                assert ast.dump(original_tree) == ast.dump(edited_tree), (
                    "Non-presentation change"
                )
            assert [
                ast.dump(n)
                for n in ast.walk(ast.parse(original))
                if isinstance(n, (ast.Import, ast.ImportFrom))
            ] == [
                ast.dump(n)
                for n in ast.walk(ast.parse(edited))
                if isinstance(n, (ast.Import, ast.ImportFrom))
            ], "Imports changed"
            assert [
                line for line in original.splitlines() if line.lstrip().startswith("#")
            ] == [
                line for line in edited.splitlines() if line.lstrip().startswith("#")
            ], "Attribution or comments changed"
            compile(edited, relative, "exec")
            destination = temp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(original)
        subprocess.run(
            [
                "git",
                "apply",
                *[
                    str(folder / name)
                    for name in manifest.get("patches", ["001-meiko-link-ui.patch"])
                ],
            ],
            cwd=temp,
            check=True,
        )
        for record in manifest["files"]:
            assert (temp / record["path"]).read_bytes() == (
                checkout / record["path"]
            ).read_bytes()
    return len(manifest["files"])


if __name__ == "__main__":
    count = validate(Path(__file__).resolve().parents[1])
    print(
        f"{count} file(s): pinned hashes, UI-only structure, interfaces, compilation and clean patch application passed."
    )
