"""Service cleaning never treats ordinary messages as removable service notices."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_moderation as fixtures


def test_command_registration_and_admin_guard(tmp_path):
    from agent.modules import moderation
    from agent.platform.service_cleaning import operate

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert "cleanservice" in commands
        denied = fixtures.FakeMessage("!cleanservice on")
        await commands["cleanservice"](
            fixtures.FakeClient(caller=fixtures.MEMBER), denied
        )
        assert await operate(ctx, -100500) == []
        request = fixtures.FakeMessage(".cleanservice joins pins")
        await commands["cleanservice"](fixtures.FakeClient(), request)
        assert await operate(ctx, -100500) == ["joins", "pins"]
        await commands["cleanservice"](
            fixtures.FakeClient(), fixtures.FakeMessage("?cleanservice invalid")
        )
        assert await operate(ctx, -100500) == ["joins", "pins"]

    asyncio.run(scenario())


def test_watcher_limits_types_checks_bot_rights_and_reports_failure(tmp_path):
    from agent.platform.service_cleaning import operate
    from agent.modules.moderation.cleaning import clean
    from pyrogram.enums import MessageServiceType as S

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        await operate(ctx, -100500, ["joins", "pins"], actor=11)
        client = fixtures.FakeClient()
        client.get_me = AsyncMock(return_value=NS(id=99))
        client.get_chat_member = AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
        client.delete_messages = AsyncMock(return_value=True)
        message = fixtures.FakeMessage("ordinary")
        assert not await clean(ctx, client, message)
        message.service = S.NEW_CHAT_MEMBERS
        assert await clean(ctx, client, message)
        client.delete_messages.assert_awaited_once_with(-100500, 100)
        client.delete_messages.reset_mock()
        message.service = S.LEFT_CHAT_MEMBERS
        assert not await clean(ctx, client, message)
        message.service = S.SUCCESSFUL_PAYMENT
        assert not await clean(ctx, client, message)
        message.service = S.PINNED_MESSAGE
        client.get_chat_member = AsyncMock(
            return_value=fixtures.member(fixtures.MEMBER)
        )
        assert not await clean(ctx, client, message)
        client.delete_messages.assert_not_awaited()
        client.get_chat_member = AsyncMock(return_value=fixtures.member(fixtures.ADMIN))
        client.delete_messages = AsyncMock(side_effect=RuntimeError("secret token"))
        assert not await clean(ctx, client, message)
        assert not message.replies
        ctx.db = NS(connected=False, _pool=None)
        client.delete_messages.reset_mock()
        assert not await clean(ctx, client, message)
        client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())


def test_pg_cleaning_shared_settings_isolation_and_audit_rollback(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.service_cleaning import operate, CleaningError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "cleaning:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = [NS(db=db) for db in dbs]
        try:
            for db in dbs:
                assert await db.connect()
            assert await operate(contexts[0], -100) == []
            await operate(contexts[0], -100, ["joins", "pins"], actor=11)
            assert await operate(contexts[1], -100) == ["joins", "pins"]
            assert await operate(contexts[1], -200) == []
            assert await operate(contexts[2], -100) == []
            await asyncio.gather(
                *(
                    operate(contexts[i % 2], -100, [kind], actor=11)
                    for i, kind in enumerate(("joins", "leaves", "pins", "photo"))
                )
            )
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_service_cleaning_revisions WHERE tenant=$1",
                        scope,
                    )
                    == 5
                )
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_cleaning_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_cleaning_audit BEFORE INSERT ON agent_service_cleaning_revisions FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_cleaning_audit()"""
                )
                before = await operate(contexts[1], -100)
                try:
                    with pytest.raises(CleaningError):
                        await operate(contexts[0], -100, [], actor=11)
                    assert await operate(contexts[1], -100) == before
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_cleaning_audit ON agent_service_cleaning_revisions"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_service_cleaning_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_service_cleaning WHERE tenant=$1",
                            db.scope,
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_cleanservice_final_rights_and_simple_saved_card(tmp_path):
    from agent.modules import moderation
    from agent.platform.service_cleaning import operate
    async def scenario():
        ctx=fixtures.ctx.__wrapped__(tmp_path)
        call=moderation.build(ctx)[1]['cleanservice']
        client=fixtures.FakeClient()
        client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
        message=fixtures.FakeMessage('/cleanservice joins')
        await call(client,message)
        assert await operate(ctx,message.chat.id)==[]
        assert 'changed' in str(message.replies[-1])
        await call(fixtures.FakeClient(),message)
        text=str(message.replies[-1])
        assert 'Saved' in text and 'Moderator' in text and 'Join notices' in text
        assert len(text)<1800 and 'Replaces selection' in text
    asyncio.run(scenario())


def test_cleanservice_read_revocation_and_raw_error_redaction(tmp_path):
    from agent.modules import moderation
    from unittest.mock import patch
    async def scenario():
        ctx=fixtures.ctx.__wrapped__(tmp_path)
        call=moderation.build(ctx)[1]['cleanservice']
        client=fixtures.FakeClient()
        client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
        message=fixtures.FakeMessage('/cleanservice')
        await call(client,message)
        assert 'changed' in str(message.replies[-1]) and 'Join notices' not in str(message.replies[-1])
        message.text='/cleanservice on'
        with patch('agent.modules.moderation.cleaning.operate',AsyncMock(side_effect=ValueError('PRIVATE_TOKEN'))):
            await call(fixtures.FakeClient(),message)
        assert 'PRIVATE_TOKEN' not in str(message.replies)
        assert 'unconfirmed' in str(message.replies[-1])
    asyncio.run(scenario())


def test_cleanservice_bot_identity_and_extras_never_change_settings(tmp_path):
    from agent.modules import moderation
    from agent.platform.service_cleaning import operate
    async def scenario():
        ctx=fixtures.ctx.__wrapped__(tmp_path)
        call=moderation.build(ctx)[1]['cleanservice']
        message=fixtures.FakeMessage('/cleanservice on')
        message.from_user=NS(id=11,is_bot=True)
        await call(fixtures.FakeClient(),message)
        assert await operate(ctx,message.chat.id)==[]
        message.from_user=NS(id=11)
        message.text='/cleanservice on invalid'
        await call(fixtures.FakeClient(),message)
        assert await operate(ctx,message.chat.id)==[]
    asyncio.run(scenario())


def test_cleanservice_committed_write_not_misreported_after_rights_or_audit_failure(tmp_path):
    from agent.modules import moderation
    from agent.platform.service_cleaning import operate
    from unittest.mock import Mock
    async def scenario():
        ctx=fixtures.ctx.__wrapped__(tmp_path)
        call=moderation.build(ctx)[1]['cleanservice']
        client=fixtures.FakeClient()
        client.get_chat_member=AsyncMock(side_effect=[fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.ADMIN),fixtures.member(fixtures.MEMBER)])
        message=fixtures.FakeMessage('/cleanservice joins')
        await call(client,message)
        assert await operate(ctx,message.chat.id)==['joins']
        assert 'Settings saved' in str(message.replies[-1]) and 'Details withheld' in str(message.replies[-1])
        ctx.chats.log=Mock(side_effect=RuntimeError('PRIVATE_AUDIT'))
        message.text='/cleanservice pins'
        await call(fixtures.FakeClient(),message)
        assert await operate(ctx,message.chat.id)==['pins']
        assert 'unconfirmed' in str(message.replies[-1])
        assert 'PRIVATE_AUDIT' not in str(message.replies)
    asyncio.run(scenario())
