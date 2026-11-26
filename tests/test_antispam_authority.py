"""Transactional protection policies and consistent group-wide off semantics."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.platform.antispam import (
    read_policy,
    change_policy,
    policy_history,
    PolicyError,
)
from agent.platform.db import Database
import test_group as fixtures


def test_off_disables_keywords_without_deleting_list(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        await change_policy(ctx, fixtures.CHAT, "keyword", "blocked", actor=11)
        policy = await change_policy(ctx, fixtures.CHAT, "off", actor=11)
        assert not any(
            policy[k]
            for k in (
                "flood_enabled",
                "duplicate_enabled",
                "links_enabled",
                "invites_enabled",
                "keywords_enabled",
            )
        )
        assert policy["blocked_keywords"] == ["blocked"]
        assert (await change_policy(ctx, fixtures.CHAT, "on", actor=11))[
            "keywords_enabled"
        ]

    asyncio.run(scenario())


def test_database_outage_never_uses_cached_policy(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        with pytest.raises(PolicyError):
            await read_policy(ctx, fixtures.CHAT)
        with pytest.raises(PolicyError):
            await change_policy(ctx, fixtures.CHAT, "links", "off", actor=11)

    asyncio.run(scenario())


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="Database required"
)
def test_pg_policy_atomic_changes_isolation_and_audit(tmp_path):
    async def scenario():
        scope = "antispam:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        try:
            contexts = []
            for i, db in enumerate(dbs):
                assert await db.connect()
                ctx = fixtures.ctx.__wrapped__(tmp_path / str(i))
                ctx.db = db
                contexts.append(ctx)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)",
                    dbs[0].name_for("chats"),
                    '{"-300":{"settings":{"antispam":{"flood_messages":19,"links_enabled":false}}}}',
                )
            imported = await read_policy(contexts[0], -300)
            assert imported["flood_messages"] == 19 and not imported["links_enabled"]
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE agent_documents SET value='{}'::jsonb WHERE name=$1",
                    dbs[0].name_for("chats"),
                )
            assert await read_policy(contexts[1], -300) == imported
            await asyncio.gather(
                change_policy(contexts[0], -100, "links", "off", actor=11),
                change_policy(contexts[1], -100, "invites", "off", actor=22),
            )
            history = await policy_history(contexts[1], -100)
            assert {r["actor"] for r in history} == {11, 22}
            state = await read_policy(contexts[0], -100)
            assert not state["links_enabled"] and not state["invites_enabled"]
            assert (await read_policy(contexts[2], -100))["links_enabled"]
            assert (await read_policy(contexts[1], -200))["links_enabled"]
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_antispam_history WHERE tenant=$1",
                        scope,
                    )
                    == 2
                )
            with pytest.raises(PolicyError):
                await change_policy(contexts[0], -100, "action", "arbitrary", actor=11)
            assert await read_policy(contexts[1], -100) == state
            await asyncio.gather(
                change_policy(contexts[0], -100, "consecutive", 7, actor=11),
                change_policy(contexts[1], -100, "floodtimer", (10, 30), actor=22),
                change_policy(
                    contexts[0], -100, "floodmode", ("tban", 259200), actor=11
                ),
                change_policy(contexts[1], -100, "clearflood", False, actor=22),
            )
            state = await read_policy(contexts[1], -100)
            assert state["consecutive_limit"] == 7 and state["timed_flood_count"] == 10
            assert state["flood_action"] == "tban" and not state["clear_flood"]
            assert not (await read_policy(contexts[2], -100)).get("consecutive_limit")
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute("""CREATE OR REPLACE FUNCTION pg_temp.reject_flood_audit() RETURNS trigger LANGUAGE plpgsql
                    AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$""")
                await conn.execute(f"""CREATE TRIGGER reject_flood_audit BEFORE INSERT ON agent_antispam_history FOR EACH ROW
                    WHEN (NEW.tenant = '{scope}') EXECUTE FUNCTION pg_temp.reject_flood_audit()""")
                try:
                    with pytest.raises(PolicyError):
                        await change_policy(
                            contexts[0], -100, "consecutive", 0, actor=11
                        )
                    assert await read_policy(contexts[1], -100) == state
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_flood_audit ON agent_antispam_history"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_antispam_policies WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("chats"),
                        )
                        await conn.execute(
                            "DELETE FROM agent_antispam_history WHERE tenant=$1",
                            db.scope,
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_sync_database_policy_writes_are_refused(tmp_path):
    from agent.platform.chats import ChatStore

    store = ChatStore(tmp_path, db=SimpleNamespace(connected=False))
    with pytest.raises(PolicyError, match="Awaited"):
        store.save_antispam(-100, {"action": "ban"})
