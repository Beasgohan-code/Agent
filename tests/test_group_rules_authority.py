"""Rules persistence, revision history and safe rendering boundaries."""

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import group
from agent.platform.db import Database
from agent.platform.group_rules import (
    read_rules,
    save_rules,
    message_chunks,
    RulesError,
)
import test_group as fixtures


def test_rules_handlers_use_shared_authority(tmp_path, monkeypatch):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        reader = AsyncMock(return_value={"body": "Canonical rule", "version": 9})
        writer = AsyncMock(return_value={"body": "", "version": 10})
        monkeypatch.setattr("agent.platform.group_rules.read_rules", reader)
        monkeypatch.setattr("agent.platform.group_rules.save_rules", writer)
        _, commands = group.build(ctx)
        message = fixtures.FakeMessage("/rules")
        await commands["rules"](fixtures.FakeClient(caller=fixtures.MEMBER), message)
        assert "Canonical rule" in message.replies[0]
        setter = fixtures.FakeMessage("/setrules clear")
        await commands["setrules"](fixtures.FakeClient(), setter)
        writer.assert_awaited_once_with(ctx, fixtures.CHAT, "", actor=11)

    asyncio.run(scenario())


def test_rules_outage_never_reads_legacy_cache_or_claims_saved(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.chats.put(fixtures.CHAT, "rules", "stale")
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        _, commands = group.build(ctx)
        for command, text in [("rules", "/rules"), ("setrules", "/setrules new")]:
            message = fixtures.FakeMessage(text)
            await commands[command](fixtures.FakeClient(), message)
            assert "unavailable" in message.replies[0]
            assert "stale" not in message.replies[0]
            assert "saved" not in message.replies[0]

    asyncio.run(scenario())


def test_emoji_rules_split_without_data_loss():
    text = "😁" * 3000
    parts = list(message_chunks(text))
    assert "".join(parts) == text and len(parts) == 2
    assert all(len(part.encode("utf-16-le")) // 2 <= 3000 for part in parts)


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="PostgreSQL required"
)
def test_pg_rules_concurrent_revisions_clear_and_import(tmp_path):
    async def scenario():
        scope = "rules-test:" + uuid.uuid4().hex
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
                    '{"-100":{"settings":{"rules":"legacy text"}}}',
                )
            assert (await read_rules(contexts[0], -100))["body"] == "legacy text"
            await asyncio.gather(
                *(
                    save_rules(contexts[i % 2], -100, f"rule {i}", actor=11 + i)
                    for i in range(12)
                )
            )
            assert (await read_rules(contexts[1], -100))["version"] == 12
            assert (await read_rules(contexts[2], -100))["body"] == ""
            assert (await read_rules(contexts[0], -200))["body"] == ""
            await save_rules(contexts[1], -100, "", actor=11)
            assert (await read_rules(contexts[0], -100))["body"] == ""
            async with dbs[0]._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT version,body FROM agent_group_rule_revisions WHERE tenant=$1 AND group_id=-100 ORDER BY version",
                    scope,
                )
                assert len(rows) == 14 and rows[0]["body"] == "legacy text"
                assert [row["version"] for row in rows] == list(range(14))
            with pytest.raises(RulesError):
                await save_rules(contexts[0], -100, "x" * 3001, actor=11)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute("""CREATE OR REPLACE FUNCTION pg_temp.reject_rules_audit() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit rejected'; END $$""")
                # Keep the trigger isolated to this test's tenant, even with shared test schemas.
                await conn.execute(f"""CREATE TRIGGER reject_rules_audit BEFORE INSERT
                    ON agent_group_rule_revisions FOR EACH ROW WHEN (NEW.tenant = '{scope}')
                    EXECUTE FUNCTION pg_temp.reject_rules_audit()""")
                try:
                    with pytest.raises(RulesError):
                        await save_rules(contexts[0], -100, "must roll back", actor=11)
                    assert (await read_rules(contexts[1], -100)) == {
                        "body": "",
                        "version": 13,
                    }
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_rules_audit ON agent_group_rule_revisions"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_group_rule_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_group_rules WHERE tenant=$1", db.scope
                        )
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("chats"),
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_public_rules_render_long_emoji_text_and_escape_group_title(tmp_path):
    from agent.utils.sender import _visible_text

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        setter = fixtures.FakeMessage("/setrules " + "😁" * 3000)
        await commands["setrules"](fixtures.FakeClient(), setter)
        reader = fixtures.FakeMessage("/rules")
        reader.chat = SimpleNamespace(id=fixtures.CHAT, title="<b>not markup</b>")
        await commands["rules"](fixtures.FakeClient(caller=fixtures.MEMBER), reader)
        assert len(reader.replies) == 2
        assert all(
            len(_visible_text(body).encode("utf-16-le")) // 2 < 4096
            for body in reader.replies
        )
        assert "&lt;b&gt;not markup&lt;/b&gt;" in reader.replies[0]

    asyncio.run(scenario())
