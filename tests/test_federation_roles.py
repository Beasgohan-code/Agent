"""Federation roles require explicit, fresh recipient consent."""

import asyncio
from types import SimpleNamespace
import pytest


def test_role_service_fails_closed_without_database():
    from agent.platform.federation_roles import change, FederationError

    async def scenario():
        with pytest.raises(FederationError, match="unavailable"):
            await change(
                SimpleNamespace(db=None),
                "invite",
                11,
                federation="00000000-0000-0000-0000-000000000001",
                target=22,
            )

    asyncio.run(scenario())


def test_pg_invitation_consent_revocation_transfer_and_audit_rollback():
    import os
    import uuid
    from agent.platform.db import Database
    from agent.platform.federations import operate
    from agent.platform.federation_roles import change, FederationError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("Database required")

    async def scenario():
        scope = "fedroles:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = []
        try:
            for db in dbs:
                assert await db.connect()
                contexts.append(SimpleNamespace(db=db))
            first = (await operate(contexts[0], "new", 11, name="Community"))["id"]
            with pytest.raises(FederationError):
                await change(contexts[0], "invite", 999, federation=first, target=22)
            invitation = await change(contexts[0], "invite", 11, target=22)
            assert (await operate(contexts[1], "admins", 22, federation=first))[
                "admins"
            ] == []
            for ctx, actor in ((contexts[1], 33), (contexts[2], 22)):
                with pytest.raises(FederationError):
                    await change(
                        ctx, "accept", actor, invitation=invitation["invitation"]
                    )
            results = await asyncio.gather(
                *(
                    change(
                        contexts[i % 2],
                        "accept",
                        22,
                        invitation=invitation["invitation"],
                    )
                    for i in range(8)
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(r, dict) for r in results) == 1
            assert (await operate(contexts[1], "admins", 22, federation=first))[
                "admins"
            ] == [22]
            assert (await operate(contexts[1], "mine", 22))[0]["id"] == first
            await change(contexts[1], "resign", 22, federation=first)
            assert not (await operate(contexts[0], "mine", 22))
            pending = await change(contexts[0], "invite", 11, target=22)
            await change(contexts[1], "demote", 11, target=22)
            with pytest.raises(FederationError):
                await change(
                    contexts[0], "accept", 22, invitation=pending["invitation"]
                )
            pending = await change(contexts[0], "invite", 11, target=22)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE agent_federation_invitations SET expires_at=now()-interval '1 second' WHERE tenant=$1",
                    scope,
                )
            with pytest.raises(FederationError):
                await change(
                    contexts[1], "accept", 22, invitation=pending["invitation"]
                )
            old = await change(contexts[0], "invite", 11, target=22)
            fresh = await change(contexts[1], "invite", 11, target=22)
            assert fresh["invitation"] != old["invitation"]
            with pytest.raises(FederationError):
                await change(contexts[0], "accept", 22, invitation=old["invitation"])
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_role_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_role_audit BEFORE INSERT ON agent_federation_history FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_role_audit()"""
                )
                try:
                    with pytest.raises(FederationError):
                        await change(
                            contexts[1], "accept", 22, invitation=fresh["invitation"]
                        )
                    assert (await operate(contexts[0], "admins", 11, federation=first))[
                        "admins"
                    ] == []
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_role_audit ON agent_federation_history"
                    )
            await change(contexts[0], "accept", 22, invitation=fresh["invitation"])
            stale_admin = await change(contexts[0], "invite", 11, target=33)
            transfer = await change(contexts[0], "invite", 11, target=22, kind="owner")
            await operate(contexts[0], "new", 22, name="Recipient other federation")
            with pytest.raises(FederationError):
                await change(
                    contexts[0], "accept", 22, invitation=transfer["invitation"]
                )
            await operate(contexts[0], "delete", 22)
            await change(contexts[1], "accept", 22, invitation=transfer["invitation"])
            assert (await operate(contexts[0], "info", 11, federation=first))[
                "owner_id"
            ] == 22
            assert not (await operate(contexts[0], "mine", 11))
            with pytest.raises(FederationError):
                await change(
                    contexts[0], "accept", 33, invitation=stale_admin["invitation"]
                )
            with pytest.raises(FederationError):
                await change(contexts[0], "demote", 11, federation=first, target=22)
            with pytest.raises(FederationError):
                await change(contexts[0], "resign", 22, federation=first)
            declined = await change(contexts[0], "invite", 22, target=33)
            await change(contexts[1], "decline", 33, invitation=declined["invitation"])
            with pytest.raises(FederationError):
                await change(
                    contexts[0], "accept", 33, invitation=declined["invitation"]
                )
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


def test_invitation_callback_requires_recipient_private_chat(monkeypatch):
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType
    from agent.platform.actions import ActionRouter
    from agent.modules.federations import roles

    async def scenario():
        ctx = SimpleNamespace(actions=ActionRouter())
        roles.build(ctx)
        mutation = AsyncMock(return_value={"kind": "admin"})
        monkeypatch.setattr(roles, "change", mutation)
        query = SimpleNamespace(
            data="fedrole:accept:bad",
            from_user=SimpleNamespace(id=22),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=-100, type=ChatType.SUPERGROUP)
            ),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        await ctx.actions.dispatch(None, query)
        mutation.assert_not_awaited()
        query.message.chat = SimpleNamespace(id=22, type=ChatType.PRIVATE)
        await ctx.actions.dispatch(None, query)
        mutation.assert_awaited_once_with(ctx, "accept", 22, invitation="bad")

    asyncio.run(scenario())


def test_failed_private_delivery_never_claims_role_changed(tmp_path, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock
    import test_group as fixtures
    from agent.platform.actions import ActionRouter
    from agent.modules.federations import roles

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.actions = ActionRouter()
        invitation = {
            "id": uuid.uuid4(),
            "name": "Community",
            "invitation": uuid.uuid4(),
            "kind": "admin",
            "target": 22,
        }
        mutation = AsyncMock(return_value=invitation)
        monkeypatch.setattr(roles, "change", mutation)
        client = SimpleNamespace(
            get_users=AsyncMock(return_value=SimpleNamespace(id=22, is_bot=False)),
            send_message=AsyncMock(side_effect=RuntimeError("private blocked")),
        )
        commands = roles.build(ctx)
        message = fixtures.FakeMessage("/fedpromote 22")
        await commands["fedpromote"](client, message)
        mutation.assert_awaited_once_with(ctx, "invite", 11, target=22, kind="admin")
        assert "No permissions changed" in message.replies[-1]
        assert "delivery was not confirmed" in message.replies[-1]

    asyncio.run(scenario())
