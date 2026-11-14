"""Local source review only; third-party execution is disabled.

Parsing source can highlight risks but cannot sandbox Python. Digest approval is
an inspection record, not permission to execute beside the bot token. load()
refuses execution until a capability-isolated external runtime exists.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .db import load_document, save_document

logger = logging.getLogger(__name__)

#: Permissions a plugin may declare. Anything else is a warning, not a rejection:
#: a typo should not brick an install, but the owner should see it.
KNOWN_PERMISSIONS = frozenset(
    {
        "messages.read",
        "messages.send",
        "files.read",
        "files.write",
        "network",
        "db.read",
        "db.write",
        "admin",
    }
)

#: Imports that make in-process code undecidable. Refused before anything runs.
BLOCKING_IMPORTS = frozenset(
    {"subprocess", "socket", "ctypes", "multiprocessing", "pty", "telnetlib"}
)

#: Builtins that turn data into code. Refused for the same reason.
BLOCKING_CALLS = frozenset({"exec", "eval", "compile", "__import__"})

#: Imports worth a human look, not a refusal.
NOTABLE_IMPORTS = frozenset(
    {"requests", "aiohttp", "urllib", "http", "ftplib", "smtplib", "importlib"}
)

#: Suffixes that mean someone meant to fetch code from the network.
REMOTE_PREFIXES = ("http://", "https://", "git@", "ssh://", "git://", "ftp://")

#: Where the loader looks once plugins are approved.
PLUGINS_DIRNAME = "plugins"


class InstallRefused(RuntimeError):
    """The install did not happen, and the message says why."""


@dataclass
class Inspection:
    """What a staged plugin is, before any of it is executed."""

    slug: str
    version: str
    digest: str
    path: Path
    commands: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    files: tuple[str, ...] = ()

    @property
    def installable(self) -> bool:
        return not self.blockers

    def summary(self) -> str:
        """One paragraph a person can decide on."""
        if self.blockers:
            return "Refused: " + "; ".join(self.blockers)
        if self.warnings:
            return "Needs review: " + "; ".join(self.warnings)
        return "No findings."


@dataclass
class Approval:
    """An owner's decision about one exact digest."""

    digest: str
    slug: str
    at: float = field(default_factory=time.time)
    by: int = 0


def _digest_files(root: Path) -> str:
    """A digest over every byte the plugin will run, paths included.

    Renaming a file changes the digest even when the source is identical, because
    the import path is part of the behaviour.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def inspect(root: Path) -> Inspection:
    """Parse a plugin directory. Never imports it, never executes it."""
    root = Path(root)
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob("*")):
        raise InstallRefused("Plugin directories must not contain symbolic links")
    if not root.is_dir():
        raise InstallRefused(f"{root.name} is not a directory")
    if not (root / "__init__.py").exists():
        raise InstallRefused(f"{root.name} has no __init__.py, so it has no build(ctx)")

    slug = root.name
    version = "unknown"
    commands: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    blockers: list[str] = []
    warnings: list[str] = []
    sources = [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]

    for path in sources:
        rel = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            blockers.append(f"{rel}: cannot be parsed ({type(exc).__name__})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules = {(node.module or "").split(".")[0]}
            else:
                modules = set()
            for module in modules:
                if module in BLOCKING_IMPORTS:
                    blockers.append(f"{rel}: imports {module}")
                elif module in NOTABLE_IMPORTS:
                    warnings.append(f"{rel}: imports {module}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in BLOCKING_CALLS:
                    blockers.append(f"{rel}: calls {node.func.id}()")
        # The manifest is read from the AST when it is a literal, so a typo or a
        # computed value is visible here rather than at first use.
        if path == root / "__init__.py":
            slug, version, commands, permissions = _read_manifest(tree, rel, blockers)

    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", slug):
        blockers.append("manifest slug must be a simple lowercase plugin name")
    for permission in permissions:
        if permission not in KNOWN_PERMISSIONS:
            warnings.append(f"declares an unknown permission {permission!r}")
    if not commands:
        warnings.append("declares no commands")

    return Inspection(
        slug=slug,
        version=version,
        digest=_digest_files(root),
        path=root,
        commands=commands,
        permissions=permissions,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        files=tuple(str(p.relative_to(root)) for p in sources),
    )


def _read_manifest(tree: ast.AST, rel: Path, blockers: list[str]):
    """Pull ``MANIFEST = PluginManifest(...)`` out of the AST, without importing."""
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "MANIFEST" for t in node.targets):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            blockers.append(f"{rel}: MANIFEST is not a PluginManifest(...) call")
            return (rel.stem, "unknown", (), ())
        values = {}
        for keyword in call.keywords:
            try:
                values[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, SyntaxError):
                blockers.append(f"{rel}: MANIFEST.{keyword.arg} is not a literal")
        slug = str(values.get("slug") or rel.stem)
        version = str(values.get("version") or "unknown")
        commands = tuple(values.get("commands") or ())
        permissions = tuple(values.get("permissions") or ())
        return (slug, version, commands, permissions)
    blockers.append(f"{rel}: has no MANIFEST")
    return (rel.stem, "unknown", (), ())


class Approvals:
    """Approved digests, in PostgreSQL like everything else that must survive."""

    NAME = "plugin_approvals"

    def __init__(self, root: Path, *, db=None) -> None:
        self.root = Path(root)
        self._db = db
        self._path = self.root / "approvals.json"
        raw = load_document(self._db, self.NAME, self._path, {})
        self._items: dict[str, Approval] = {}
        for digest, item in (raw or {}).items():
            try:
                self._items[digest] = Approval(
                    digest=digest,
                    slug=item["slug"],
                    at=float(item.get("at", 0.0)),
                    by=int(item.get("by", 0)),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("ignoring a malformed plugin approval")

    def _save(self) -> None:
        save_document(
            self._db,
            self.NAME,
            self._path,
            {
                digest: {"slug": a.slug, "at": a.at, "by": a.by}
                for digest, a in self._items.items()
            },
        )

    def approve(self, inspection: Inspection, *, by: int = 0) -> Approval:
        if inspection.blockers:
            raise InstallRefused(
                f"{inspection.slug} cannot be approved: " + "; ".join(inspection.blockers)
            )
        approval = Approval(digest=inspection.digest, slug=inspection.slug, by=by)
        self._items[inspection.digest] = approval
        self._save()
        logger.info("approved plugin %s at %s…", inspection.slug, inspection.digest[:12])
        return approval

    def revoke(self, digest: str) -> bool:
        if self._items.pop(digest, None) is None:
            return False
        self._save()
        return True

    def is_approved(self, inspection: Inspection) -> bool:
        return inspection.digest in self._items

    def for_slug(self, slug: str) -> tuple[Approval, ...]:
        return tuple(a for a in self._items.values() if a.slug == slug)

    def all(self) -> tuple[Approval, ...]:
        return tuple(self._items.values())


def stage(source: str | Path, *, root: Path) -> Inspection:
    """Copy a local plugin into staging and inspect it, or refuse.

    A remote source is refused *before* anything is downloaded: the reason is not
    that downloading is hard, it is that the code would then run beside the token.
    """
    text = str(source)
    if text.startswith(REMOTE_PREFIXES):
        raise InstallRefused(
            "Plugins are loaded into this process, next to the bot token and every "
            "user's files, so a plugin fetched over the network cannot be made safe "
            "by approving it. Point me at a directory you already reviewed, or run "
            "the code in its own process."
        )
    source_path = Path(source)
    inspection = inspect(source_path)
    if inspection.blockers:
        raise InstallRefused(
            f"{inspection.slug} was not staged: " + "; ".join(inspection.blockers)
        )
    target = Path(root) / "staging" / inspection.digest
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, target, ignore=shutil.ignore_patterns("__pycache__"))
    inspection.path = target
    return inspection


def activate(inspection: Inspection, *, root: Path, approvals: Approvals) -> Path:
    """Move an approved, unchanged staging copy into the plugin directory."""
    current = inspect(inspection.path)
    if current.digest != inspection.digest or current.slug != inspection.slug or current.blockers:
        raise InstallRefused("Staged plugin changed; inspect and approve it again")
    if not approvals.is_approved(current):
        raise InstallRefused(
            f"{inspection.slug} has not been approved; approve digest "
            f"{inspection.digest[:12]}… first"
        )
    landing = Path(root) / PLUGINS_DIRNAME / inspection.slug
    if landing.exists():
        if _digest_files(landing) == inspection.digest:
            return landing
        raise InstallRefused(
            f"{inspection.slug} is already installed with a different digest; "
            "revoke and stage the new version"
        )
    landing.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inspection.path, landing, ignore=shutil.ignore_patterns("__pycache__"))
    logger.info("activated plugin %s", inspection.slug)
    return landing


def load(root: Path, *, ctx, registry, approvals: Approvals) -> tuple[str, ...]:
    """External execution is disabled until a capability process boundary exists.

    AST inspection and digest review are not a sandbox. Retain the entry point
    so older integrations receive an explicit refusal rather than importing code.
    """
    raise InstallRefused(
        "Third-party execution is disabled: a capability-isolated process runtime "
        "is required. Inspection and Owner approval do not sandbox Python."
    )
