"""Filter commands must not confirm stale process-local writes."""

import asyncio
from types import SimpleNamespace
import test_groups as fixtures
from agent.modules import filters


def test_configured_outage_refuses_filter_reads_and_writes(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.set_filter(-100900, "hello", "stale", by=11)
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        _, commands = filters.build(ctx)
        for name, text in [
            ("filter", "/filter hello new"),
            ("filters", "/filters"),
            ("stopfilter", "/stopfilter hello"),
        ]:
            message = fixtures.FakeMessage(text)
            await commands[name](fixtures.FakeClient(), message)
            assert "unavailable" in message.replies[-1].lower()
        message = fixtures.FakeMessage("hello")
        await filters.watch(ctx)(fixtures.FakeClient(), message)
        assert not message.replies

    asyncio.run(scenario())


def test_pg_filter_atomic_limit_order_isolation_and_audit_rollback(tmp_path):
    import os
    import uuid
    import json
    import pytest
    from agent.platform.db import Database
    from agent.platform.group_filters import operate, FilterError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("Database required")

    async def scenario():
        scope = "filters-test:" + uuid.uuid4().hex
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
            legacy = {f"key{i}": str(i) for i in range(99)}
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)",
                    dbs[0].name_for("chats"),
                    json.dumps({"-100": {"settings": {"filters": legacy}}}),
                )
            assert await operate(contexts[0], -100) == legacy
            results = await asyncio.gather(
                *(
                    operate(
                        contexts[i % 2], -100, name=f"new{i}", body="answer", actor=11
                    )
                    for i in range(12)
                ),
                return_exceptions=True,
            )
            assert sum(result is True for result in results) == 1
            assert sum(isinstance(result, FilterError) for result in results) == 11
            assert len(await operate(contexts[1], -100)) == 100
            assert await operate(contexts[2], -100) == {}
            assert await operate(contexts[0], -200) == {}
            await operate(contexts[0], -100, name="key0", body="updated", actor=11)
            before = await operate(contexts[1], -100)
            assert list(before) == list(await operate(contexts[0], -100))
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute("""CREATE OR REPLACE FUNCTION pg_temp.reject_filter_audit() RETURNS trigger LANGUAGE plpgsql
                    AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$""")
                await conn.execute(f"""CREATE TRIGGER reject_filter_audit BEFORE INSERT ON agent_group_filter_revisions
                    FOR EACH ROW WHEN (NEW.tenant = '{scope}') EXECUTE FUNCTION pg_temp.reject_filter_audit()""")
                try:
                    with pytest.raises(FilterError):
                        await operate(contexts[0], -100, name="key0", actor=11)
                    assert await operate(contexts[1], -100) == before
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_filter_audit ON agent_group_filter_revisions"
                    )
            assert await operate(contexts[1], -100, name="key0", actor=11)
            assert "key0" not in await operate(contexts[0], -100)
            assert not await operate(contexts[0], -100, name="missing", actor=11)
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_group_filter_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_group_filters WHERE tenant=$1", db.scope
                        )
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("chats"),
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_bot_owner_without_group_privilege_cannot_manage_filters(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        from dataclasses import replace

        ctx.settings = replace(ctx.settings, owner_id=11)
        _, commands = filters.build(ctx)
        request = fixtures.FakeMessage("/filter hello no")
        await commands["filter"](fixtures.FakeClient(caller=fixtures.MEMBER), request)
        assert not ctx.chats.filters(-100900)
        assert "administrators" in request.replies[-1]

    asyncio.run(scenario())
