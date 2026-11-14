"""Installing a plugin is a review, not a copy.

A plugin runs in this process beside the bot token, so these tests pin the two
claims the installer makes: unsafe constructs are refused before anything is
imported, and code whose digest was never approved is never loaded.
"""

import sys
import textwrap

import pytest

from agent.platform import installer
from agent.platform.installer import Approvals, InstallRefused, inspect, load, stage
from agent.platform.manifest import PluginRegistry


def plugin(tmp_path, *, body="", name="hello", manifest=None, extra=""):
    root = tmp_path / "src" / name
    root.mkdir(parents=True)
    manifest = manifest or textwrap.dedent(
        """\
        MANIFEST = PluginManifest(
            slug="hello",
            name="Hello",
            version="1.0.0",
            description="Says hello.",
            commands=("hello",),
            permissions=("messages.send",),
        )
        """
    )
    (root / "__init__.py").write_text(
        textwrap.dedent(
            """\
            from agent.platform.manifest import PluginManifest

            """
        )
        + manifest
        + textwrap.dedent(
            """\

            def build(ctx):
                async def hello(client, message):
                    await message.reply("hi")
                return MANIFEST, {"hello": hello}
            """
        )
        + extra
        + body
    )
    return root


# --- inspection ------------------------------------------------------------


def test_a_clean_plugin_has_no_findings(tmp_path):
    found = inspect(plugin(tmp_path))

    assert found.installable
    assert found.blockers == ()
    assert found.slug == "hello"
    assert found.commands == ("hello",)
    assert found.summary() == "No findings."


def test_exec_is_a_hard_blocker(tmp_path):
    found = inspect(plugin(tmp_path, extra="\ndef run(code):\n    return eval(code)\n"))

    assert not found.installable
    assert "calls eval()" in " ".join(found.blockers)


def test_spawning_a_process_is_a_hard_blocker(tmp_path):
    found = inspect(plugin(tmp_path, extra="\nimport subprocess\n"))

    assert not found.installable
    assert "imports subprocess" in " ".join(found.blockers)


def test_network_imports_are_a_warning_not_a_refusal(tmp_path):
    found = inspect(plugin(tmp_path, extra="\nimport aiohttp\n"))

    assert found.installable
    assert "imports aiohttp" in " ".join(found.warnings)
    assert found.summary().startswith("Needs review")


def test_an_unknown_permission_is_flagged(tmp_path):
    found = inspect(
        plugin(
            tmp_path,
            manifest='MANIFEST = PluginManifest(slug="hello", name="H", version="1",'
            ' description="d", commands=("hello",), permissions=("root",))\n',
        )
    )

    assert any("unknown permission" in w for w in found.warnings)


def test_a_plugin_without_a_manifest_cannot_be_staged(tmp_path):
    root = plugin(tmp_path)
    (root / "__init__.py").write_text("def build(ctx):\n    return None, {}\n")

    found = inspect(root)
    assert not found.installable
    assert any("no MANIFEST" in b for b in found.blockers)

    with pytest.raises(InstallRefused, match="no MANIFEST"):
        stage(root, root=tmp_path / "store")


def test_an_unparseable_plugin_is_refused_at_inspection(tmp_path):
    root = plugin(tmp_path)
    (root / "__init__.py").write_text("def build(:\n")

    found = inspect(root)
    assert not found.installable


def test_the_digest_changes_when_a_byte_changes(tmp_path):
    root = plugin(tmp_path)
    first = inspect(root).digest
    (root / "helper.py").write_text("X = 1\n")

    assert inspect(root).digest != first


# --- staging ---------------------------------------------------------------


def test_a_remote_source_is_refused_with_the_reason(tmp_path):
    with pytest.raises(InstallRefused) as error:
        stage("https://github.com/someone/plugin", root=tmp_path / "store")

    message = str(error.value)
    assert "cannot be made safe" in message
    assert "own process" in message
    assert not (tmp_path / "store" / "staging").exists()


def test_staging_copies_the_plugin_without_importing_it(tmp_path):
    root = plugin(tmp_path)
    found = stage(root, root=tmp_path / "store")

    assert found.path.exists()
    assert found.path != root
    assert (found.path / "__init__.py").exists()
    assert "agent_plugin_hello" not in sys.modules


def test_an_unsafe_plugin_is_never_staged(tmp_path):
    root = plugin(tmp_path, extra="\nimport subprocess\n")

    with pytest.raises(InstallRefused):
        stage(root, root=tmp_path / "store")


# --- approvals -------------------------------------------------------------


def test_approval_is_tied_to_the_digest(tmp_path):
    root = plugin(tmp_path)
    store = tmp_path / "store"
    found = stage(root, root=store)
    approvals = Approvals(store)
    approvals.approve(found, by=42)

    assert approvals.is_approved(found) is True

    (root / "__init__.py").write_text((root / "__init__.py").read_text() + "\n# edited\n")
    tampered = stage(root, root=store)

    assert tampered.digest != found.digest
    assert approvals.is_approved(tampered) is False


def test_an_unsafe_plugin_cannot_be_approved(tmp_path):
    found = inspect(plugin(tmp_path, extra="\nimport socket\n"))

    with pytest.raises(InstallRefused):
        Approvals(tmp_path / "store").approve(found)


def test_approvals_survive_with_a_database(tmp_path):
    class FakeDB:
        connected = True

        def __init__(self):
            self.docs = {}

        def get(self, name, default=None):
            return self.docs.get(name, default)

        def has(self, name):
            return name in self.docs

        def save(self, name, value):
            self.docs[name] = value

    db = FakeDB()
    found = inspect(plugin(tmp_path))
    Approvals(tmp_path / "store", db=db).approve(found, by=42)

    assert Approvals(tmp_path / "store", db=db).is_approved(found)


def test_activation_needs_approval(tmp_path):
    store = tmp_path / "store"
    found = stage(plugin(tmp_path), root=store)

    with pytest.raises(InstallRefused, match="not been approved"):
        installer.activate(found, root=store, approvals=Approvals(store))


def test_activation_lands_the_plugin(tmp_path):
    store = tmp_path / "store"
    found = stage(plugin(tmp_path), root=store)
    approvals = Approvals(store)
    approvals.approve(found)

    landing = installer.activate(found, root=store, approvals=approvals)

    assert landing == store / "plugins" / "hello"
    assert (landing / "__init__.py").exists()


# --- loading ---------------------------------------------------------------


@pytest.mark.parametrize("approved", [False, True])
def test_external_execution_refused_even_after_approval(tmp_path, approved):
    store = tmp_path / "store"
    found = stage(plugin(tmp_path), root=store)
    approvals = Approvals(store)
    if approved:
        approvals.approve(found)
        installer.activate(found, root=store, approvals=approvals)
    registry = PluginRegistry()
    with pytest.raises(InstallRefused, match="capability-isolated"):
        load(store, ctx=None, registry=registry, approvals=approvals)
    assert registry.manifests() == []
    assert "agent_plugin_hello" not in sys.modules


def test_manifest_cannot_escape_install_root(tmp_path):
    root = plugin(tmp_path, manifest='MANIFEST = PluginManifest(slug="../../outside", commands=("hello",))\n')
    with pytest.raises(InstallRefused, match='simple lowercase'):
        stage(root, root=tmp_path / 'store')


def test_symlinked_plugin_contents_refused(tmp_path):
    root = plugin(tmp_path)
    secret = tmp_path / 'not-plugin.txt'
    secret.write_text('private bytes')
    (root / 'linked.txt').symlink_to(secret)
    with pytest.raises(InstallRefused, match='symbolic links'):
        stage(root, root=tmp_path / 'store')


def test_activation_reinspects_staged_bytes(tmp_path):
    store = tmp_path / 'store'
    found = stage(plugin(tmp_path), root=store)
    approvals = Approvals(store)
    approvals.approve(found)
    source = found.path / '__init__.py'
    source.write_text(source.read_text() + '\nCHANGED = True\n')
    with pytest.raises(InstallRefused, match='changed'):
        installer.activate(found, root=store, approvals=approvals)
