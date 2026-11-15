"""Cross-client clone reservations use committed encrypted database state."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.modules.clone.store import Clone, CloneStore
from agent.platform.db import Database
from agent.platform.secrets import SecretBox


KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_database_clone_mutations_require_awaiting(tmp_path):
    store = CloneStore(tmp_path, db=SimpleNamespace(connected=False))
    with pytest.raises(RuntimeError, match="Awaited"):
        store.add(Clone(bot_id=111111111, owner_id=7, token="secret"))
    assert not store.all()


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="PostgreSQL required"
)
def test_atomic_clone_capacity_updates_and_isolation(tmp_path):
    async def scenario():
        scope = "clone-atomic:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":other")
        ]
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            stores = [
                CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY))
                for i, db in enumerate(dbs)
            ]

            async def add(i):
                try:
                    await stores[i % 2].aadd(
                        Clone(
                            bot_id=111111111 + i, owner_id=7, token="sensitive-token"
                        ),
                        owner_limit=3,
                        total_limit=5,
                    )
                    return True
                except RuntimeError as exc:
                    assert "capacity" in str(exc)
                    return False

            assert sum(await asyncio.gather(*(add(i) for i in range(30)))) == 3
            assert len(await stores[1].aall()) == 3
            assert not await stores[2].aall()
            ids = [r.bot_id for r in await stores[0].aall()]
            await asyncio.gather(
                stores[0].aupdate(ids[0], username="first"),
                stores[1].aupdate(ids[1], disabled=True),
            )
            records = {r.bot_id: r for r in await stores[0].aall()}
            assert records[ids[0]].username == "first"
            assert records[ids[1]].disabled
            # A different owner cannot exceed the deployment ceiling either.
            for i in range(2):
                await stores[1].aadd(
                    Clone(bot_id=222222220 + i, owner_id=8, token="sensitive-token"),
                    owner_limit=3,
                    total_limit=5,
                )
            with pytest.raises(RuntimeError, match="capacity"):
                await stores[0].aadd(
                    Clone(bot_id=333333333, owner_id=9, token="secret"),
                    owner_limit=3,
                    total_limit=5,
                )
            await stores[1].aremove(ids[0])
            assert len(await stores[0].aall()) == 4
            async with dbs[0]._pool.acquire() as conn:
                raw = await conn.fetchval(
                    "SELECT value::text FROM agent_documents WHERE name=$1",
                    dbs[0].name_for("clones"),
                )
            assert "sensitive-token" not in raw
            assert "token_enc" in raw
            assert "clones" not in dbs[0]._pending
            # A corrupt record must not disappear or silently free capacity.
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE agent_documents SET value=value || '[{}]'::jsonb WHERE name=$1",
                    dbs[0].name_for("clones"),
                )
            with pytest.raises(RuntimeError, match="invalid or undecryptable"):
                await stores[1].aremove(ids[1])
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT jsonb_array_length(value) FROM agent_documents WHERE name=$1",
                        dbs[0].name_for("clones"),
                    )
                    == 5
                )
            assert not list(tmp_path.rglob("*.json"))
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("clones"),
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_database_outage_never_uses_local_clone_state(tmp_path):
    async def scenario():
        store = CloneStore(
            tmp_path, db=SimpleNamespace(connected=False), box=SecretBox(KEY)
        )
        for operation in (
            store.aall(),
            store.aremove(111111111),
            store.aadd(
                Clone(bot_id=111111111, owner_id=7, token="secret"),
                owner_limit=3,
                total_limit=5,
            ),
        ):
            with pytest.raises(RuntimeError, match="unavailable"):
                await operation
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(scenario())


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="PostgreSQL required"
)
@pytest.mark.parametrize("operation", ["disable", "remove"])
def test_worker_supervisor_observes_changes_from_another_controller(
    tmp_path, operation
):
    from test_clone import build, TOKEN_A, MEMBER

    async def scenario():
        scope = "clone-controller:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=scope, required=True)
            for _ in range(2)
        ]
        manager = None
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            stores = [
                CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY))
                for i, db in enumerate(dbs)
            ]
            ctx, _, _ = build(tmp_path / "controller")
            manager = ctx.clones
            manager._store = stores[0]
            record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A)
            await stores[0].aadd(record, owner_limit=3, total_limit=5)
            await manager.start(record)
            assert manager.is_running(record.bot_id)
            if operation == "disable":
                await stores[1].aupdate(record.bot_id, disabled=True)
            else:
                await stores[1].aremove(record.bot_id)
            await manager.supervise()
            assert not manager.is_running(record.bot_id)
        finally:
            if manager:
                await manager.stop_all()
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("clones"),
                        )
                await db.close()

    asyncio.run(scenario())
