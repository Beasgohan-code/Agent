"""Command cleanup is post-handler, opt-in and confined to known commands."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_moderation as fixtures


def test_command_cleanup_runs_after_success_and_preserves_results(tmp_path):
    from agent.modules.moderation.command_cleaning import wrap
    from agent.platform.command_cleaning import operate
    from pyrogram.enums import ChatType

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        await operate(ctx, -100500, True, actor=11)
        seen = []

        async def handler(client, message):
            seen.append("handler")
            return 42

        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        client.get_chat_member = AsyncMock(return_value=fixtures.member(fixtures.ADMIN))

        async def delete(chat, mid):
            seen.append("delete")
            return True

        client.delete_messages = AsyncMock(side_effect=delete)
        for prefix in "/!.?":
            message = fixtures.FakeMessage(prefix + "help")
            assert await wrap(ctx, handler)(client, message) == 42
            assert seen[-2:] == ["handler", "delete"]
        await operate(ctx, -100500, False, actor=11)
        client.delete_messages.reset_mock()
        await wrap(ctx, handler)(client, fixtures.FakeMessage("!help"))
        client.delete_messages.assert_not_awaited()
        await operate(ctx, -100500, True, actor=11)
        message = fixtures.FakeMessage("!help")
        message.chat = NS(id=11, type=ChatType.PRIVATE)
        await wrap(ctx, handler)(client, message)
        client.delete_messages.assert_not_awaited()
        client.delete_messages = AsyncMock(side_effect=RuntimeError("secret-token"))
        assert await wrap(ctx, handler)(client, fixtures.FakeMessage("?help")) == 42
        ctx.db = NS(connected=False, _pool=None)
        client.delete_messages.reset_mock()
        assert await wrap(ctx, handler)(client, fixtures.FakeMessage("?help")) == 42
        client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())


def test_cleancommand_registration_and_permissions(tmp_path):
    from agent.modules import moderation
    from agent.platform.command_cleaning import operate

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert {"cleancommand", "keepcommand"} <= commands.keys()
        await commands["cleancommand"](
            fixtures.FakeClient(caller=fixtures.MEMBER),
            fixtures.FakeMessage("!cleancommand all"),
        )
        assert not await operate(ctx, -100500)
        await commands["cleancommand"](
            fixtures.FakeClient(), fixtures.FakeMessage(".cleancommand all")
        )
        assert await operate(ctx, -100500)
        await commands["keepcommand"](
            fixtures.FakeClient(), fixtures.FakeMessage("?keepcommand all")
        )
        assert not await operate(ctx, -100500)

    asyncio.run(scenario())


def test_pg_command_cleaning_atomic_history_and_isolation(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.command_cleaning import operate, CleaningError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "command-cleaning:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = [NS(db=db) for db in dbs]
        try:
            for db in dbs:
                assert await db.connect()
            assert not await operate(contexts[0], -100)
            await operate(contexts[0], -100, True, actor=11)
            assert await operate(contexts[1], -100)
            assert not await operate(contexts[2], -100)
            assert not await operate(contexts[1], -200)
            await asyncio.gather(
                *(
                    operate(contexts[i % 2], -100, bool(i % 2), actor=11)
                    for i in range(6)
                )
            )
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_command_cleaning_revisions WHERE tenant=$1",
                        scope,
                    )
                    == 7
                )
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_command_clean_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_command_clean_audit BEFORE INSERT ON agent_command_cleaning_revisions FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_command_clean_audit()"""
                )
                before = await operate(contexts[1], -100)
                try:
                    with pytest.raises(CleaningError):
                        await operate(contexts[0], -100, not before, actor=11)
                    assert await operate(contexts[1], -100) == before
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_command_clean_audit ON agent_command_cleaning_revisions"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_command_cleaning_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_command_cleaning WHERE tenant=$1",
                            db.scope,
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_cleanup_never_hides_handler_exception_or_runs_without_bot_rights(tmp_path):
    import pytest
    from agent.modules.moderation.command_cleaning import wrap
    from agent.platform.command_cleaning import operate

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        await operate(ctx, -100500, True, actor=11)
        client = fixtures.FakeClient()
        client.delete_messages = AsyncMock()
        handler = AsyncMock(side_effect=ValueError("handler failed"))
        with pytest.raises(ValueError):
            await wrap(ctx, handler)(client, fixtures.FakeMessage("!help"))
        client.delete_messages.assert_not_awaited()
        client.get_me = AsyncMock(return_value=NS(id=99))
        client.get_chat_member = AsyncMock(
            return_value=fixtures.member(fixtures.MEMBER)
        )
        await wrap(ctx, AsyncMock())(client, fixtures.FakeMessage("!help"))
        client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())
