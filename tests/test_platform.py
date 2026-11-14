"""Platform core: registry lifecycle, job queue, storage and signed links."""

import asyncio

import pytest

from agent.platform.jobs import JobQueue, JobState
from agent.platform.links import LinkError, LinkStore
from agent.platform.manifest import PluginManifest, PluginRegistry
from agent.platform.storage import QuotaExceeded, Storage, safe_filename


def manifest(slug="demo", commands=("demo",)):
    return PluginManifest(slug=slug, name=slug, version="1.0.0", description="", commands=commands)


# --- registry --------------------------------------------------------------


def test_registry_registers_and_resolves():
    registry = PluginRegistry()
    handler = object()
    registry.register(manifest(), {"demo": handler})

    assert registry.handler_for("demo") is handler
    assert registry.active_commands() == ["demo"]


def test_disabled_plugin_exposes_no_handlers():
    registry = PluginRegistry()
    registry.register(manifest(), {"demo": object()})

    registry.disable("demo")

    assert registry.handler_for("demo") is None
    assert registry.active_commands() == []
    assert registry.is_enabled("demo") is False


def test_re_enabling_restores_handlers():
    registry = PluginRegistry()
    registry.register(manifest(), {"demo": object()})
    registry.disable("demo")

    registry.enable("demo")

    assert registry.handler_for("demo") is not None


def test_command_collisions_are_rejected():
    registry = PluginRegistry()
    registry.register(manifest("a", ("shared",)), {"shared": object()})

    with pytest.raises(ValueError, match="collision"):
        registry.register(manifest("b", ("shared",)), {"shared": object()})


def test_declared_command_without_handler_is_rejected():
    registry = PluginRegistry()

    with pytest.raises(ValueError, match="no handler"):
        registry.register(manifest("c", ("declared",)), {})


def test_duplicate_slug_is_rejected():
    registry = PluginRegistry()
    registry.register(manifest(), {"demo": object()})

    with pytest.raises(ValueError, match="already registered"):
        registry.register(manifest(), {"demo": object()})


# --- jobs ------------------------------------------------------------------


def test_job_completes_and_reports_progress():
    async def scenario():
        queue = JobQueue(concurrency=2)

        async def runner(job):
            job.progress = 0.5

        job = queue.submit("demo", 7, runner)
        await job.task
        return job

    job = asyncio.run(scenario())

    assert job.state is JobState.DONE
    assert job.progress == 1.0


def test_job_failure_is_recorded_not_raised():
    async def scenario():
        queue = JobQueue()

        async def runner(_job):
            raise RuntimeError("boom")

        job = queue.submit("demo", 7, runner)
        await job.task
        return job

    job = asyncio.run(scenario())

    assert job.state is JobState.FAILED
    assert "boom" in job.error


def test_job_cancel_only_for_owner():
    async def scenario():
        queue = JobQueue(concurrency=1)
        gate = asyncio.Event()

        async def runner(_job):
            await gate.wait()

        job = queue.submit("demo", owner_id=7, runner=runner)
        await asyncio.sleep(0)

        wrong = queue.cancel(job.id, owner_id=99)
        right = queue.cancel(job.id, owner_id=7)
        return job, wrong, right

    job, wrong, right = asyncio.run(scenario())

    assert wrong is False
    assert right is True
    assert job.state is JobState.CANCELLED


# --- storage ---------------------------------------------------------------


def test_storage_round_trip(tmp_path):
    store = Storage(tmp_path / "s")
    saved = store.save_bytes(1, "../../etc/passwd", b"hello")

    assert saved.name == "etc_passwd"
    assert store.get(saved.id).size == 5
    assert store.path_for(saved).read_bytes() == b"hello"
    assert store.owner_of(saved.id) == 1
    assert store.list_owned(1)


def test_quota_is_enforced(tmp_path):
    store = Storage(tmp_path / "s", per_user_quota_mb=1)
    store.save_bytes(1, "a.bin", b"x" * 600_000)

    with pytest.raises(QuotaExceeded):
        store.save_bytes(1, "b.bin", b"y" * 600_000)


def test_delete_requires_owner(tmp_path):
    store = Storage(tmp_path / "s")
    saved = store.save_bytes(1, "a.bin", b"x")

    assert store.delete(saved.id, owner_id=2) is False
    assert store.delete(saved.id, owner_id=1) is True
    assert store.get(saved.id) is None


def test_prune_removes_old_files(tmp_path):
    store = Storage(tmp_path / "s")
    saved = store.save_bytes(1, "old.bin", b"x")

    removed = store.prune(retention_days=0, now=saved.created_at + 10)

    assert removed == [saved.id]
    assert store.get(saved.id) is None


def test_unsafe_filenames_are_neutralised():
    assert "/" not in safe_filename("../../x/y.mp4")
    assert safe_filename("") == "file.bin"


# --- links -----------------------------------------------------------------


def test_link_round_trip(tmp_path):
    links = LinkStore(tmp_path / "l", "secret")

    record = links.create("file123", owner_id=5)

    assert links.resolve(record.token).file_id == "file123"
    assert links.verify_signature(record.token)


def test_revoked_link_is_rejected(tmp_path):
    links = LinkStore(tmp_path / "l", "secret")
    record = links.create("f", 1)
    assert links.revoke(record.token, owner_id=1)

    with pytest.raises(LinkError, match="revoked"):
        links.resolve(record.token)


def test_only_owner_can_revoke(tmp_path):
    links = LinkStore(tmp_path / "l", "secret")
    record = links.create("f", owner_id=1)

    assert links.revoke(record.token, owner_id=2) is False


def test_tampered_signature_is_rejected(tmp_path):
    links = LinkStore(tmp_path / "l", "secret")
    record = links.create("f", 1)
    payload, _, _sig = record.token.rsplit(".", 1)[0], None, record.token.rsplit(".", 1)[1]

    forged = f"{payload}.{'A' * len(_sig)}"

    with pytest.raises(LinkError, match="bad signature"):
        links.resolve(forged)


def test_expired_link_is_rejected(tmp_path):
    links = LinkStore(tmp_path / "l", "secret")
    record = links.create("f", 1, ttl_hours=1)
    record.expires_at = 0  # simulate the clock moving past expiry
    links._links[record.token] = record

    with pytest.raises(LinkError, match="expired"):
        links.resolve(record.token)
