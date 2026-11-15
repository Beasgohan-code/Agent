"""Administrator changes require current Telegram privileges."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import test_group as fixtures
from agent.modules import group


def test_admin_commands_registered_and_promotion_denied_without_rights(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        assert {
            "promote",
            "demote",
            "adminlist",
            "admincache",
            "anonadmin",
            "adminerror",
        } <= commands.keys()
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        client.promote_chat_member = AsyncMock()
        await commands["promote"](client, fixtures.FakeMessage("/promote 22"))
        client.promote_chat_member.assert_not_awaited()

    asyncio.run(scenario())


def test_promote_demote_and_target_forms(tmp_path):
    from pyrogram.enums import ChatMemberStatus as Status
    from agent.modules.group.admin import resolve

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        rights = SimpleNamespace(
            can_promote_members=True, can_manage_chat=True, can_delete_messages=True
        )
        target = SimpleNamespace(id=22)
        client = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(id=99)),
            get_users=AsyncMock(return_value=target),
            promote_chat_member=AsyncMock(return_value=True),
        )
        target_member = SimpleNamespace(status=Status.MEMBER, can_be_edited=True)

        async def member(chat, uid):
            if uid == 22:
                return target_member
            return SimpleNamespace(status=Status.ADMINISTRATOR, privileges=rights)

        client.get_chat_member = member
        await commands["promote"](client, fixtures.FakeMessage("/promote @someone"))
        call = client.promote_chat_member.await_args
        assert call.args == (fixtures.CHAT, 22)
        assert call.kwargs["privileges"].can_delete_messages
        assert not call.kwargs["privileges"].can_promote_members
        target_member.status = Status.ADMINISTRATOR
        await commands["demote"](client, fixtures.FakeMessage("/demote 22"))
        assert not client.promote_chat_member.await_args.kwargs[
            "privileges"
        ].can_manage_chat
        target_member.can_be_edited = False
        client.promote_chat_member.reset_mock()
        await commands["demote"](client, fixtures.FakeMessage("/demote 22"))
        client.promote_chat_member.assert_not_awaited()
        message = fixtures.FakeMessage("/promote")
        message.entities = [SimpleNamespace(user=target)]
        assert (await resolve(client, message)).id == 22

    asyncio.run(scenario())


def test_anonymous_setting_and_silent_denials(tmp_path):
    from agent.platform.admin_settings import options
    from agent.modules.moderation import is_moderator

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        message = fixtures.FakeMessage("/pin")
        message.sender_chat = SimpleNamespace(id=fixtures.CHAT)
        assert not await is_moderator(client, message, ctx=ctx)
        await options(ctx, fixtures.CHAT, setting="anonadmin", enabled=True, actor=11)
        assert await is_moderator(client, message, ctx=ctx)
        message.sender_chat.id = -123
        assert not await is_moderator(client, message, ctx=ctx)
        await options(ctx, fixtures.CHAT, setting="adminerror", enabled=False, actor=11)
        _, commands = group.build(ctx)
        request = fixtures.FakeMessage("/promote 22")
        await commands["promote"](client, request)
        assert not request.replies
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        message.sender_chat.id = fixtures.CHAT
        assert not await is_moderator(client, message, ctx=ctx)

    asyncio.run(scenario())


def test_pg_admin_settings_shared_and_audit_rollback(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.admin_settings import options, AdminStateError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "admin-test:" + uuid.uuid4().hex
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
            assert await options(contexts[0], -100) == {
                "anonadmin": False,
                "adminerror": True,
            }
            await asyncio.gather(
                options(contexts[0], -100, setting="anonadmin", enabled=True, actor=11),
                options(
                    contexts[1], -100, setting="adminerror", enabled=False, actor=11
                ),
            )
            assert await options(contexts[1], -100) == {
                "anonadmin": True,
                "adminerror": False,
            }
            assert not (await options(contexts[2], -100))["anonadmin"]
            assert not (await options(contexts[0], -200))["anonadmin"]
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_admin_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_admin_audit BEFORE INSERT ON agent_admin_setting_history FOR EACH ROW WHEN (NEW.tenant = '{scope}') EXECUTE FUNCTION pg_temp.reject_admin_audit()"""
                )
                try:
                    with pytest.raises(AdminStateError):
                        await options(
                            contexts[0],
                            -100,
                            setting="anonadmin",
                            enabled=False,
                            actor=11,
                        )
                    assert (await options(contexts[1], -100))["anonadmin"]
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_admin_audit ON agent_admin_setting_history"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_admin_setting_history WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_admin_settings WHERE tenant=$1", db.scope
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_adminlist_and_refresh_are_live_and_group_scoped(tmp_path):
    from pyrogram.enums import ChatMemberStatus

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        client = fixtures.FakeClient()
        calls = []

        async def members(chat_id, **kwargs):
            calls.append(chat_id)
            yield SimpleNamespace(
                user=SimpleNamespace(id=22, first_name="Admin"),
                status=ChatMemberStatus.ADMINISTRATOR,
            )

        client.get_chat_members = members
        for command in ("admincache", "adminlist", "adminlist"):
            message = fixtures.FakeMessage("/" + command)
            await commands[command](client, message)
            assert message.replies
        assert calls == [fixtures.CHAT] * 3

    asyncio.run(scenario())
