"""Forum management checks actual chat state and both live topic privileges."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import test_moderation as fixtures
from agent.modules import group


def client():
    bot = fixtures.FakeClient()
    bot.get_chat = AsyncMock(return_value=NS(is_forum=True))
    bot.get_me = AsyncMock(return_value=NS(id=99))

    async def member(chat, user):
        return NS(status=fixtures.ADMIN, privileges=NS(can_manage_topics=True))

    bot.get_chat_member = AsyncMock(side_effect=member)
    bot.create_forum_topic = AsyncMock(return_value=NS(id=45))
    for name in (
        "edit_forum_topic",
        "close_forum_topic",
        "reopen_forum_topic",
        "edit_general_forum_topic",
        "close_general_forum_topic",
        "reopen_general_forum_topic",
    ):
        setattr(bot, name, AsyncMock(return_value=True))
    return bot


def test_topic_commands_are_registered_and_use_current_topic(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        assert {
            "newtopic",
            "renametopic",
            "closetopic",
            "reopentopic",
        } <= commands.keys()
        bot = client()
        for command, body, method in [
            ("newtopic", "Games", "create_forum_topic"),
            ("renametopic", "New name", "edit_forum_topic"),
            ("closetopic", "", "close_forum_topic"),
            ("reopentopic", "", "reopen_forum_topic"),
        ]:
            request = fixtures.FakeMessage("!" + command + " " + body)
            request.message_thread_id = 45
            await commands[command](bot, request)
            getattr(bot, method).assert_awaited_once()
            assert "confirmed" in request.replies[-1].lower()
        bot.edit_forum_topic.assert_awaited_once_with(-100500, 45, title="New name")
        bot.create_forum_topic.assert_awaited_once_with(-100500, title="Games")
        request = fixtures.FakeMessage(".closetopic")
        request.message_thread_id = 1
        await commands["closetopic"](bot, request)
        bot.close_general_forum_topic.assert_awaited_once_with(-100500)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        "caller",
        "bot",
        "forum",
        "anonymous",
        "missing_thread",
        "bad_title",
        "api_false",
        "api_exception",
    ],
)
def test_topic_failures_are_safe_and_truthful(tmp_path, failure):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        bot = client()
        request = fixtures.FakeMessage("?renametopic Good title")
        request.message_thread_id = 45
        if failure in ("caller", "bot"):

            async def member(chat, user):
                return NS(
                    status=fixtures.ADMIN,
                    privileges=NS(
                        can_manage_topics=(user != (11 if failure == "caller" else 99))
                    ),
                )

            bot.get_chat_member.side_effect = member
        elif failure == "forum":
            bot.get_chat.return_value = NS(is_forum=False)
        elif failure == "anonymous":
            request.sender_chat = NS(id=-100500)
        elif failure == "missing_thread":
            request.message_thread_id = None
        elif failure == "bad_title":
            request.text = "?renametopic " + "a" * 129
        elif failure == "api_false":
            bot.edit_forum_topic.return_value = False
        elif failure == "api_exception":
            bot.edit_forum_topic.side_effect = RuntimeError("token-secret")
        await commands["renametopic"](bot, request)
        if failure not in ("api_false", "api_exception"):
            bot.edit_forum_topic.assert_not_awaited()
        assert request.replies
        assert "token-secret" not in request.replies[-1]
        assert "change confirmed" not in request.replies[-1].lower()

    asyncio.run(scenario())


def test_action_topic_controls_and_greetings_use_current_destination(tmp_path):
    from agent.platform.action_topics import operate
    from agent.modules import welcome
    import test_groups as greetings
    from pyrogram.enums import ChatMemberStatus as S

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        assert {"actiontopic", "setactiontopic"} <= commands.keys()
        request = fixtures.FakeMessage("!setactiontopic")
        request.message_thread_id = 45
        await commands["setactiontopic"](client(), request)
        assert await operate(ctx, -100500) == 45
        assert await operate(ctx, -100900) is None
        ctx.chats.set_greeting(-100900, "welcome", "Hello {name}")
        await operate(ctx, -100900, 45, actor=11)
        bot = greetings.FakeClient()
        bot.send_message = AsyncMock(return_value=True)
        await welcome.watch(ctx)(
            bot, greetings.update(new_status=S.MEMBER, old_status=S.LEFT)
        )
        assert bot.send_message.await_args.kwargs["message_thread_id"] == 45
        bot.send_message = AsyncMock(side_effect=RuntimeError("secret"))
        await welcome.watch(ctx)(
            bot, greetings.update(new_status=S.MEMBER, old_status=S.LEFT)
        )
        assert bot.send_message.await_count == 1  # no fallback into another topic

    asyncio.run(scenario())


def test_pg_action_topic_isolation_atomic_audit_and_outage(tmp_path):
    import os
    import uuid
    from agent.platform.db import Database
    from agent.platform.action_topics import operate, ActionTopicError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("Database required")

    async def scenario():
        scope = "action-topic:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        contexts = [NS(db=db) for db in dbs]
        try:
            for db in dbs:
                assert await db.connect()
            assert await operate(contexts[0], -100) is None
            await operate(contexts[0], -100, 45, actor=11)
            assert await operate(contexts[1], -100) == 45
            assert await operate(contexts[1], -200) is None
            assert await operate(contexts[2], -100) is None
            await asyncio.gather(
                *(operate(contexts[i % 2], -100, 100 + i, actor=11) for i in range(5))
            )
            before = await operate(contexts[1], -100)
            async with dbs[0]._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_action_topic_revisions WHERE tenant=$1",
                        scope,
                    )
                    == 6
                )
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_actiontopic_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_actiontopic_audit BEFORE INSERT ON agent_action_topic_revisions FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_actiontopic_audit()"""
                )
                try:
                    with pytest.raises(ActionTopicError):
                        await operate(contexts[0], -100, 1, actor=11)
                    assert await operate(contexts[1], -100) == before
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_actiontopic_audit ON agent_action_topic_revisions"
                    )
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_action_topic_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_action_topics WHERE tenant=$1", db.scope
                        )
            for db in dbs:
                await db.close()
        with pytest.raises(ActionTopicError):
            await operate(NS(db=NS(connected=False, _pool=None)), -100)

    asyncio.run(scenario())
