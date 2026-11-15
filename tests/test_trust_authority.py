"""Trust must not mutate stale cache during a configured database outage."""

import asyncio
from types import SimpleNamespace
import test_moderation as fixtures
from agent.modules import moderation


def test_trust_outage_does_not_confirm_or_mutate(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        _, commands = moderation.build(ctx)
        message = fixtures.FakeMessage("/approve", reply=True)
        await commands["approve"](fixtures.FakeClient(), message)
        assert "unavailable" in message.replies[-1].lower()
        assert not ctx.chats.is_trusted(-100500, 22)

    asyncio.run(scenario())


def test_pg_trust_concurrency_import_isolation_and_audit_rollback(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.group_trust import trusted_members, trust_history, TrustError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "trust-test:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = []
        try:
            for i, db in enumerate(dbs):
                assert await db.connect()
                ctx = fixtures.ctx.__wrapped__(tmp_path / str(i))
                ctx.db = db
                contexts.append(ctx)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)",
                    dbs[0].name_for("chats"),
                    '{"-100":{"members":{"22":{"trusted":true},"33":{"trusted":false}}}}',
                )
            assert await trusted_members(contexts[0], -100) == {22}
            await asyncio.gather(
                *(
                    trusted_members(contexts[i % 2], -100, toggle=22, actor=11)
                    for i in range(12)
                )
            )
            assert await trusted_members(contexts[1], -100) == {22}
            assert await trusted_members(contexts[2], -100) == set()
            assert await trusted_members(contexts[0], -200) == set()
            history = await trust_history(contexts[1], -100)
            assert len(history) == 10 and history[0]["action"] == "approve"
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT version FROM agent_group_trust WHERE tenant=$1 AND group_id=-100",
                        scope,
                    )
                    == 12
                )
                await conn.execute("""CREATE OR REPLACE FUNCTION pg_temp.reject_trust_audit() RETURNS trigger LANGUAGE plpgsql
                    AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$""")
                await conn.execute(f"""CREATE TRIGGER reject_trust_audit BEFORE INSERT ON agent_group_trust_revisions
                    FOR EACH ROW WHEN (NEW.tenant = '{scope}') EXECUTE FUNCTION pg_temp.reject_trust_audit()""")
                try:
                    with pytest.raises(TrustError):
                        await trusted_members(contexts[0], -100, toggle=22, actor=11)
                    assert await trusted_members(contexts[1], -100) == {22}
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_trust_audit ON agent_group_trust_revisions"
                    )
            await trusted_members(contexts[1], -100, toggle=22, actor=11)
            assert await trusted_members(contexts[0], -100) == set()
            await asyncio.gather(
                *(
                    trusted_members(
                        contexts[i % 2], -100, toggle=22, actor=11, approved=True
                    )
                    for i in range(12)
                )
            )
            assert await trusted_members(contexts[1], -100) == {22}
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT version FROM agent_group_trust WHERE tenant=$1 AND group_id=-100",
                        scope,
                    )
                    == 14
                )
            await asyncio.gather(
                *(
                    trusted_members(
                        contexts[i % 2], -100, toggle=22, actor=11, approved=False
                    )
                    for i in range(12)
                )
            )
            assert await trusted_members(contexts[1], -100) == set()
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT version FROM agent_group_trust WHERE tenant=$1 AND group_id=-100",
                        scope,
                    )
                    == 15
                )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_group_trust_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_group_trust WHERE tenant=$1", db.scope
                        )
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("chats"),
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_trust_requires_actual_group_rights_not_bot_ownership(tmp_path):
    from dataclasses import replace

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.settings = replace(ctx.settings, owner_id=11)
        _, commands = moderation.build(ctx)
        request = fixtures.FakeMessage("/approve", reply=True)
        await commands["approve"](fixtures.FakeClient(caller=fixtures.MEMBER), request)
        assert not ctx.chats.is_trusted(-100500, 22)

    asyncio.run(scenario())


def test_watcher_skips_punishment_when_trust_cannot_be_verified(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        monkeypatch.setattr(
            moderation,
            "read_policy",
            AsyncMock(return_value={"links_enabled": True, "action": "ban"}),
        )
        message = fixtures.FakeMessage("https://spam.example", uid=22)
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        await moderation.watch(ctx)(client, message)
        assert not client.calls
        assert not ctx.chats.warnings_of(-100500, 22)

    asyncio.run(scenario())
