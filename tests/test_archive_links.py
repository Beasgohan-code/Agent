"""Archive range links never decode user-supplied channel IDs or execute refs."""

import asyncio
import os
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatType, ChatMemberStatus
from agent.modules.filestore.channel_links import build
from agent.platform.archive_links import create
from agent.platform.deeplinks import DeepLinkRouter


def request(text="/custom_batch 10 12", uid=11, mid=1):
    return NS(
        text=text,
        id=mid,
        from_user=NS(id=uid),
        chat=NS(id=uid, type=ChatType.PRIVATE),
        reply=AsyncMock(),
    )


def context(db=None):
    return NS(
        db=db,
        settings=NS(owner_id=11, storage_channel=-100),
        deeplinks=DeepLinkRouter(),
    )


def client():
    return NS(
        get_chat=AsyncMock(
            return_value=NS(type=ChatType.CHANNEL, has_protected_content=False)
        ),
        get_me=AsyncMock(return_value=NS(id=99, username="MeikoBot")),
        get_chat_member=AsyncMock(
            return_value=NS(status=ChatMemberStatus.ADMINISTRATOR)
        ),
        get_messages=AsyncMock(return_value=[NS(id=i) for i in range(10, 13)]),
        copy_message=AsyncMock(return_value=NS(id=50)),
    )


def test_unconfigured_or_unauthorized_creation_has_no_telegram_effects():
    async def scenario():
        for uid in (11, 22):
            ctx = context()
            commands = build(ctx)
            bot = client()
            msg = request(uid=uid)
            await commands["custom_batch"](bot, msg)
            bot.get_messages.assert_not_awaited()
            bot.copy_message.assert_not_awaited()
            assert msg.reply.await_count == 1

    asyncio.run(scenario())


def test_pg_archive_link_creation_redemption_scope_replay_and_partial_delivery():
    from agent.platform.db import Database

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "archive-links:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope + ":clone")
        ]
        try:
            for db in dbs:
                assert await db.connect()
            ctx = context(dbs[0])
            commands = build(ctx)
            bot = client()
            msg = request()
            await commands["custom_batch"](bot, msg)
            assert "archive_" in str(msg.reply.await_args.args[0])
            async with dbs[0]._pool.acquire() as conn:
                token = await conn.fetchval(
                    "SELECT token FROM agent_archive_links WHERE tenant=$1", scope
                )
            clone = context(dbs[1])
            build(clone)
            await clone.deeplinks.dispatch(
                bot, request("/start", 22), "archive_" + token
            )
            bot.copy_message.assert_not_awaited()
            recipient = request("/start", 22)
            await asyncio.gather(
                *(
                    ctx.deeplinks.dispatch(bot, recipient, "archive_" + token)
                    for _ in range(4)
                )
            )
            assert bot.copy_message.await_count == 3
            await ctx.deeplinks.dispatch(bot, recipient, "archive_" + token)
            assert bot.copy_message.await_count == 3
            bot.copy_message.reset_mock()
            bot.copy_message.side_effect = [NS(id=1), TimeoutError("secret"), NS(id=2)]
            partial = request("/start", 22, mid=2)
            await ctx.deeplinks.dispatch(bot, partial, "archive_" + token)
            assert bot.copy_message.await_count == 2
            assert "1 copies confirmed" in str(partial.reply.await_args.args[0])
            assert "secret" not in str(partial.reply.await_args.args[0])
            async with dbs[0]._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT outcome,delivered FROM agent_archive_deliveries WHERE tenant=$1 ORDER BY message_id",
                    scope,
                )
                assert [(r["outcome"], r["delivered"]) for r in rows] == [
                    ("applied", 3),
                    ("unconfirmed", 1),
                ]
                await conn.execute(
                    "UPDATE agent_archive_links SET expires_at=now()-interval '1 second' WHERE tenant=$1",
                    scope,
                )
            bot.copy_message.reset_mock()
            await ctx.deeplinks.dispatch(
                bot, request("/start", 22, mid=3), "archive_" + token
            )
            bot.copy_message.assert_not_awaited()
            with pytest.raises(ValueError):
                await create(ctx, 11, -100, 12, 10)
        finally:
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_archive_deliveries WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_archive_links WHERE tenant=$1", db.scope
                        )
                await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "protected",
        "caller_not_admin",
        "bot_not_admin",
        "missing_message",
        "service_message",
    ],
)
def test_bad_archive_sources_never_create_link_or_copy(monkeypatch, case):
    async def scenario():
        ctx = context(NS(connected=True, _pool=object()))
        bot = client()
        if case == "protected":
            bot.get_chat.return_value.has_protected_content = True
        elif case in ("caller_not_admin", "bot_not_admin"):

            async def member(channel, uid):
                denied = 11 if case == "caller_not_admin" else 99
                return NS(
                    status=ChatMemberStatus.MEMBER
                    if uid == denied
                    else ChatMemberStatus.ADMINISTRATOR
                )

            bot.get_chat_member.side_effect = member
        elif case == "missing_message":
            bot.get_messages.return_value = [
                NS(id=10),
                NS(id=11, empty=True),
                NS(id=12),
            ]
        else:
            bot.get_messages.return_value = [
                NS(id=10),
                NS(id=11, service=True),
                NS(id=12),
            ]
        creator = AsyncMock()
        monkeypatch.setattr("agent.modules.filestore.channel_links.create", creator)
        await build(ctx)["custom_batch"](bot, request())
        creator.assert_not_awaited()
        bot.copy_message.assert_not_awaited()

    asyncio.run(scenario())


def test_pg_archive_revoke_authority_and_mid_delivery_stop():
    from agent.platform.archive_links import revoke
    from agent.platform.db import Database

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="archive-revoke:" + uuid.uuid4().hex,
            required=True,
        )
        try:
            assert await db.connect()
            ctx = context(db)
            bot = client()
            commands = build(ctx)
            token = await create(ctx, 11, -100, 10, 12)
            with pytest.raises(ValueError):
                await revoke(ctx, 22, token)
            copied = []

            async def copy(chat, channel, mid):
                copied.append(mid)
                if len(copied) == 1:
                    await revoke(ctx, 11, token)
                return NS(id=50)

            bot.copy_message.side_effect = copy
            msg = request("/start", 22)
            await ctx.deeplinks.dispatch(bot, msg, "archive_" + token)
            assert copied == [10]
            assert "1 copies confirmed" in str(msg.reply.await_args.args[0])
            bot.copy_message.reset_mock()
            await ctx.deeplinks.dispatch(
                bot, request("/start", 22, mid=2), "archive_" + token
            )
            bot.copy_message.assert_not_awaited()
            assert await revoke(ctx, 11, token) is False
            second = await create(ctx, 11, -100, 10, 10)
            req = request("/custom_batch revoke " + second)
            await commands["custom_batch"](bot, req)
            assert "revoked" in str(req.reply.await_args.args[0]).lower()
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_archive_deliveries WHERE tenant=$1", db.scope
                    )
                    await conn.execute(
                        "DELETE FROM agent_archive_links WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())


def test_custom_selection_parser_rejects_ambiguous_or_oversize_batches():
    from agent.modules.filestore.channel_links import selection

    assert selection(["ids", "10", "30", "14"]) == [10, 30, 14]
    assert selection(["10", "12"]) == [10, 11, 12]
    for args in (
        ["ids"],
        ["ids", "10", "10"],
        ["ids", "0"],
        ["ids", "١"],
        ["12", "10"],
        ["1", "51"],
        ["ids"] + [str(i) for i in range(1, 52)],
    ):
        with pytest.raises(ValueError):
            selection(args)


def test_pg_custom_selection_persists_and_delivers_only_selected_messages():
    from agent.platform.db import Database

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="archive-selection:" + uuid.uuid4().hex,
            required=True,
        )
        try:
            assert await db.connect()
            ctx = context(db)
            commands = build(ctx)
            bot = client()
            bot.get_messages.return_value = [NS(id=10), NS(id=90), NS(id=14)]
            await commands["custom_batch"](bot, request("/custom_batch ids 10 90 14"))
            bot.get_messages.assert_awaited_once_with(-100, [10, 90, 14])
            async with db._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT token,message_ids FROM agent_archive_links WHERE tenant=$1",
                    db.scope,
                )
            assert row["message_ids"] == [10, 90, 14]
            await ctx.deeplinks.dispatch(
                bot, request("/start", 22), "archive_" + row["token"]
            )
            assert [call.args[2] for call in bot.copy_message.await_args_list] == [
                10,
                90,
                14,
            ]
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_archive_deliveries WHERE tenant=$1", db.scope
                    )
                    await conn.execute(
                        "DELETE FROM agent_archive_links WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())


def test_archive_message_references_are_bound_to_configured_channel():
    from agent.modules.filestore.channel_links import message_selection

    channel = -10012345
    assert message_selection(
        request("/custom_batch https://t.me/c/12345/10 https://t.me/c/12345/12"),
        channel,
    ) == ([10, 11, 12], False)
    assert message_selection(
        request("/custom_batch ids https://t.me/c/12345/20 10"), channel
    ) == ([20, 10], True)
    forwarded = request("/custom_batch")
    forwarded.reply_to_message = NS(
        forward_from_chat=NS(id=channel), forward_from_message_id=42
    )
    assert message_selection(forwarded, channel) == ([42], True)
    forwarded.reply_to_message.forward_from_chat.id = -10067890
    with pytest.raises(ValueError):
        message_selection(forwarded, channel)
    for value in (
        "https://t.me/c/67890/10",
        "https://t.me/c/12345/10?single",
        "https://evil.example/c/12345/10",
        "https://t.me/c/12345/0",
        "https://t.me/c/12345/2147483648",
    ):
        with pytest.raises(ValueError):
            message_selection(request("/custom_batch ids " + value), channel)
    with pytest.raises(ValueError):
        message_selection(request("/custom_batch"), channel)


@pytest.mark.asyncio
async def test_forwarded_archive_creation_uses_same_validated_delivery_path():
    ctx = context()
    bot = client()
    message = request("/custom_batch")
    message.reply_to_message = NS(
        forward_from_chat=NS(id=-100), forward_from_message_id=10
    )
    # No database means fail closed even for a correctly forwarded archive item.
    await build(ctx)["custom_batch"](bot, message)
    bot.get_messages.assert_not_awaited()
    bot.copy_message.assert_not_awaited()
    assert message.reply.await_count == 1


def test_pg_archive_item_ledger_retains_confirmed_and_uncertain_copies():
    from agent.platform.db import Database

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="archive-ledger:" + uuid.uuid4().hex,
            required=True,
        )
        try:
            assert await db.connect()
            ctx = context(db)
            build(ctx)
            bot = client()
            token = await create(ctx, 11, -100, 10, 12)
            bot.copy_message.side_effect = [NS(id=77), TimeoutError("uncertain")]
            await ctx.deeplinks.dispatch(
                bot, request("/start", 22, 600), "archive_" + token
            )
            async with db._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT source_id,outcome,destination_id FROM agent_archive_delivery_items WHERE tenant=$1 ORDER BY source_id",
                    db.scope,
                )
            assert [dict(row) for row in rows] == [
                dict(source_id=10, outcome="applied", destination_id=77),
                dict(source_id=11, outcome="unconfirmed", destination_id=None),
            ]
            await ctx.deeplinks.dispatch(
                bot, request("/start", 22, 600), "archive_" + token
            )
            assert bot.copy_message.await_count == 2
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_archive_deliveries WHERE tenant=$1", db.scope
                    )
                    await conn.execute(
                        "DELETE FROM agent_archive_links WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())


def test_link_options_are_bounded_and_not_silently_ignored():
    from agent.modules.filestore.channel_links import link_options

    assert link_options(["10", "12", "--uses=1", "--hours=2"]) == (["10", "12"], 2, 1)
    for args in (
        ["--uses=0"],
        ["--hours=169"],
        ["--uses=10001"],
        ["--other=1"],
        ["--uses=1", "--uses=2"],
    ):
        with pytest.raises(ValueError):
            link_options(args)


def test_pg_archive_use_limit_is_atomic_for_concurrent_requests():
    from agent.platform.db import Database

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="archive-limits:" + uuid.uuid4().hex,
            required=True,
        )
        try:
            assert await db.connect()
            ctx = context(db)
            build(ctx)
            bot = client()
            token = await create(ctx, 11, -100, 10, 10, hours=2, max_uses=1)
            await asyncio.gather(
                *(
                    ctx.deeplinks.dispatch(
                        bot, request("/start", 22, mid), "archive_" + token
                    )
                    for mid in (701, 702)
                )
            )
            assert bot.copy_message.await_count == 1
            async with db._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT uses FROM agent_archive_links WHERE tenant=$1 AND token=$2",
                        db.scope,
                        token,
                    )
                    == 1
                )
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_archive_deliveries WHERE tenant=$1", db.scope
                    )
                    await conn.execute(
                        "DELETE FROM agent_archive_links WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())
