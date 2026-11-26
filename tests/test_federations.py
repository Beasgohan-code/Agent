"""Federation authority must fail closed and serialize ownership/membership."""

import asyncio
from types import SimpleNamespace
import pytest


def test_federation_database_is_required():
    from agent.platform.federations import FederationError, operate

    async def scenario():
        for db in (None, SimpleNamespace(connected=False, _pool=None)):
            with pytest.raises(FederationError, match="unavailable"):
                await operate(SimpleNamespace(db=db), "new", 11, name="Community")

    asyncio.run(scenario())


def test_join_requires_live_chat_owner_even_for_bot_owner(tmp_path, monkeypatch):
    from dataclasses import replace
    from unittest.mock import AsyncMock
    import test_group as fixtures
    from agent.modules import federations

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.settings = replace(ctx.settings, owner_id=11)
        operation = AsyncMock()
        monkeypatch.setattr(federations, "operate", operation)
        _, commands = federations.build(ctx)
        for command, text in [
            ("joinfed", "/joinfed 00000000-0000-0000-0000-000000000001"),
            ("leavefed", "/leavefed"),
        ]:
            message = fixtures.FakeMessage(text)
            await commands[command](fixtures.FakeClient(), message)
            assert "chat owner" in message.replies[-1]
        operation.assert_not_awaited()

    asyncio.run(scenario())


def test_pg_federation_uniqueness_isolation_permissions_and_rollback(tmp_path):
    import os
    import uuid
    from agent.platform.db import Database
    from agent.platform.federations import operate as service_operate, FederationError
    from pyrogram.enums import ChatMemberStatus
    from unittest.mock import AsyncMock

    owner_client = SimpleNamespace(
        get_chat_member=AsyncMock(
            return_value=SimpleNamespace(status=ChatMemberStatus.OWNER)
        )
    )

    async def operate(*args, **kwargs):
        return await service_operate(*args, client=owner_client, **kwargs)

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("Database required")

    async def scenario():
        scope = "federations-test:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = []
        try:
            for db in dbs:
                assert await db.connect()
                contexts.append(SimpleNamespace(db=db))
            results = await asyncio.gather(
                *(
                    operate(contexts[i % 2], "new", 11, name="Community")
                    for i in range(12)
                ),
                return_exceptions=True,
            )
            rows = [r for r in results if isinstance(r, dict)]
            assert (
                len(rows) == 1
                and sum(isinstance(r, FederationError) for r in results) == 11
            )
            first = rows[0]["id"]
            second = (await operate(contexts[0], "new", 22, name="Other"))["id"]
            await operate(contexts[0], "reason", 11, federation=first, enabled=True)
            await operate(contexts[1], "notify", 11, federation=first, enabled=False)
            preferences = await operate(contexts[1], "info", 11, federation=first)
            assert preferences["require_reason"] and not preferences["notify_owner"]
            for action in ("reason", "notify"):
                with pytest.raises(FederationError):
                    await operate(contexts[0], action, 22, federation=first, enabled=True)
                with pytest.raises(FederationError):
                    await operate(contexts[2], action, 11, federation=first, enabled=True)

            with pytest.raises(FederationError):
                await operate(contexts[2], "info", 11, federation=first)
            with pytest.raises(FederationError):
                await operate(
                    contexts[0], "rename", 22, federation=first, name="Stolen"
                )
            assert (await operate(contexts[2], "new", 11, name="Clone"))["id"] != first
            results = await asyncio.gather(
                operate(contexts[0], "join", 11, federation=first, chat=-100),
                operate(contexts[1], "join", 22, federation=second, chat=-100),
                return_exceptions=True,
            )
            assert sum(isinstance(r, dict) for r in results) == 1
            current = await operate(contexts[1], "chat", 33, chat=-100)
            assert current["id"] in (first, second)
            assert len(await operate(contexts[1], "mine", 11)) == 1
            assert (await operate(contexts[1], "admins", 33, federation=first))[
                "owner"
            ] == 11
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_fed_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_fed_audit BEFORE INSERT ON agent_federation_history FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_fed_audit()"""
                )
                try:
                    with pytest.raises(FederationError):
                        await operate(
                            contexts[0], "rename", 11, name="Should roll back"
                        )
                    assert (await operate(contexts[1], "info", 11, federation=first))[
                        "name"
                    ] == "Community"
                    with pytest.raises(FederationError):
                        await operate(
                            contexts[0], "join", 11, federation=first, chat=-200
                        )
                    with pytest.raises(FederationError):
                        await operate(contexts[1], "chat", 11, chat=-200)
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_fed_audit ON agent_federation_history"
                    )
            await operate(contexts[0], "leave", 33, chat=-100)
            await operate(contexts[0], "join", 11, federation=first, chat=-100)
            await operate(contexts[0], "delete", 11, federation=first)
            with pytest.raises(FederationError):
                await operate(contexts[1], "chat", 11, chat=-100)
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_federation_history WHERE tenant=$1 AND fed_id=$2",
                        scope,
                        first,
                    )
                    == 0
                )
            await operate(contexts[0], "new", 11, name="Replacement")
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_federations WHERE tenant=$1", db.scope
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_delete_requires_explicit_confirmation_and_personal_identity(
    tmp_path, monkeypatch
):
    import uuid
    from unittest.mock import AsyncMock
    import test_group as fixtures
    from agent.modules import federations

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        identity = uuid.uuid4()
        operation = AsyncMock(
            return_value={"id": identity, "name": "<test>", "owner_id": 11}
        )
        monkeypatch.setattr(federations, "operate", operation)
        _, commands = federations.build(ctx)
        message = fixtures.FakeMessage("/delfed")
        await commands["delfed"](fixtures.FakeClient(), message)
        assert operation.await_args.args[1] == "info"
        assert "&lt;test&gt;" in message.replies[-1]
        message = fixtures.FakeMessage("/delfed confirm " + str(identity))
        await commands["delfed"](fixtures.FakeClient(), message)
        assert operation.await_args.args[1] == "delete"
        operation.reset_mock()
        message = fixtures.FakeMessage("/newfed Example")
        message.sender_chat = SimpleNamespace(id=fixtures.CHAT)
        await commands["newfed"](fixtures.FakeClient(), message)
        operation.assert_not_awaited()

    asyncio.run(scenario())


def test_federation_preferences_commands_validate_and_do_not_claim_delivery(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock
    import test_group as fixtures
    from agent.modules import federations

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        state = {
            "id": "test-fed",
            "name": "Community",
            "owner_id": 11,
            "require_reason": True,
            "notify_owner": False,
        }
        operation = AsyncMock(return_value=state)
        monkeypatch.setattr(federations, "operate", operation)
        _, commands = federations.build(ctx)
        assert {"fedreason", "fednotif", "quietfed"} <= commands.keys()
        for command, action in [("fedreason", "reason"), ("fednotif", "notify")]:
            request = fixtures.FakeMessage("!" + command + " on")
            await commands[command](fixtures.FakeClient(), request)
            operation.assert_awaited_with(
                ctx, action, 11, enabled=True, federation=None
            )
            assert "not available" in request.replies[-1]
        operation.reset_mock()
        await commands["fedreason"](
            fixtures.FakeClient(), fixtures.FakeMessage("?fedreason maybe")
        )
        operation.assert_not_awaited()
        request = fixtures.FakeMessage(".quietfed on")
        await commands["quietfed"](fixtures.FakeClient(), request)
        operation.assert_not_awaited()  # fixture is admin, not live chat owner

    asyncio.run(scenario())
