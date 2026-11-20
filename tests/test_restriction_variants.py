"""Explicit timed/delete/silent actions must preserve permission boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import test_moderation as fixtures
from agent.modules import moderation


def test_variant_registration_and_denied_caller(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert {
            "tban",
            "tmute",
            "dban",
            "dmute",
            "dkick",
            "sban",
            "smute",
            "skick",
            "kickme",
        } <= commands.keys()
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        for name in (
            "tban",
            "tmute",
            "dban",
            "dmute",
            "dkick",
            "sban",
            "smute",
            "skick",
        ):
            message = fixtures.FakeMessage("/" + name + " 1h", reply=True)
            await commands[name](client, message)
        assert not client.calls

    asyncio.run(scenario())


def test_admin_lists_hide_anonymous_identities(tmp_path):
    import test_group as group_fixtures
    from agent.modules import group

    async def scenario():
        ctx = group_fixtures.ctx.__wrapped__(tmp_path)
        _, commands = group.build(ctx)
        client = group_fixtures.FakeClient()

        async def members(*args, **kwargs):
            yield SimpleNamespace(
                user=SimpleNamespace(id=987654321, first_name="Hidden identity"),
                status=fixtures.ADMIN,
                privileges=SimpleNamespace(is_anonymous=True),
            )
            yield SimpleNamespace(
                user=SimpleNamespace(id=22, first_name="Visible admin"),
                status=fixtures.ADMIN,
                privileges=SimpleNamespace(is_anonymous=False),
            )

        client.get_chat_members = members
        for command in ("admins", "adminlist"):
            message = group_fixtures.FakeMessage("/" + command)
            await commands[command](client, message)
            assert "987654321" not in message.replies[-1]
            assert "Hidden identity" not in message.replies[-1]
            assert "Visible admin" in message.replies[-1]

    asyncio.run(scenario())


def client_with_rights():
    client = fixtures.FakeClient()
    client.get_me = AsyncMock(return_value=SimpleNamespace(id=99))

    async def member(chat, uid):
        if uid in (11, 99):
            return fixtures.member(fixtures.ADMIN)
        return fixtures.member(fixtures.MEMBER)

    client.get_chat_member = member
    client.get_users = AsyncMock(return_value=SimpleNamespace(id=22))
    client.ban_chat_member = AsyncMock(return_value=True)
    client.unban_chat_member = AsyncMock(return_value=True)
    client.restrict_chat_member = AsyncMock(return_value=True)
    client.delete_messages = AsyncMock(return_value=True)
    return client


def test_timed_and_delete_variants_confirm_actions_and_parse_targets(tmp_path):
    async def scenario():
        for command in ("tban", "tmute", "dban", "dmute", "dkick"):
            ctx = fixtures.ctx.__wrapped__(tmp_path / command)
            _, commands = moderation.build(ctx)
            client = client_with_rights()
            is_delete = command.startswith("d")
            message = fixtures.FakeMessage(
                "/"
                + command
                + (" reason <tag>" if is_delete else " @someone 5w reason <tag>"),
                reply=is_delete,
            )
            if is_delete:
                message.reply_to_message.id = 10
            await commands[command](client, message)
            if command in ("tban", "dban", "dkick"):
                client.ban_chat_member.assert_awaited_once()
                assert ("until_date" in client.ban_chat_member.await_args.kwargs) == (
                    command == "tban"
                )
            else:
                client.restrict_chat_member.assert_awaited_once()
                assert (
                    "until_date" in client.restrict_chat_member.await_args.kwargs
                ) == (command == "tmute")
            assert "&lt;tag&gt;" in message.replies[-1]
            if is_delete:
                client.delete_messages.assert_awaited_once_with(-100500, 10)
            else:
                client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())


def test_silent_variants_and_partial_cleanup_are_honest(tmp_path):
    async def scenario():
        for command in ("sban", "smute", "skick"):
            ctx = fixtures.ctx.__wrapped__(tmp_path / command)
            _, commands = moderation.build(ctx)
            client = client_with_rights()
            message = fixtures.FakeMessage(
                "/" + command + (" 2h reason" if command != "skick" else " reason"),
                reply=True,
            )
            message.reply_to_message.id = 10
            await commands[command](client, message)
            assert not message.replies
            assert [
                call.args[1] for call in client.delete_messages.await_args_list
            ] == [10, 100]
            if command == "skick":
                client.unban_chat_member.assert_awaited_once()
        ctx = fixtures.ctx.__wrapped__(tmp_path / "partial")
        _, commands = moderation.build(ctx)
        client = client_with_rights()
        client.delete_messages.return_value = False
        message = fixtures.FakeMessage("/sban 22")
        await commands["sban"](client, message)
        assert "cleanup was not confirmed" in message.replies[-1]

    asyncio.run(scenario())


def test_kickme_targets_only_caller_and_handles_partial_kick(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        client = client_with_rights()
        message = fixtures.FakeMessage("/kickme", uid=22)
        await commands["kickme"](client, message)
        client.ban_chat_member.assert_awaited_once_with(-100500, 22)
        client.unban_chat_member.assert_awaited_once_with(-100500, 22)
        client = client_with_rights()
        client.unban_chat_member.return_value = False
        message = fixtures.FakeMessage("/dkick", reply=True)
        message.reply_to_message.id = 10
        await commands["dkick"](client, message)
        assert "may still be banned" in message.replies[-1]
        client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())


def test_invalid_duration_protected_target_and_database_outage(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        for text in (
            "/tban 22",
            "/tban 22 1s",
            "/tban 22 30s",
            "/tmute 22 99999w",
            "/tban -1 1h",
            "/tban 99 1h",
            "/dban 22",
        ):
            client = client_with_rights()
            await commands[text.split()[0][1:]](client, fixtures.FakeMessage(text))
            client.ban_chat_member.assert_not_awaited()
            client.restrict_chat_member.assert_not_awaited()
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        client = client_with_rights()
        message = fixtures.FakeMessage("/tban 22 1h")
        await commands["tban"](client, message)
        client.ban_chat_member.assert_not_awaited()
        assert "unavailable" in message.replies[-1]

    asyncio.run(scenario())


def test_pg_restriction_intents_replay_isolation_and_outcomes():
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.restriction_cases import begin, finish, history, CaseError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("Database required")

    async def scenario():
        scope = "restriction-test:" + uuid.uuid4().hex
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
                    begin(contexts[i % 2], -100, 1, 11, 22, "tban", 3600, "reason")
                    for i in range(12)
                ),
                return_exceptions=True,
            )
            ids = [r for r in results if isinstance(r, uuid.UUID)]
            assert (
                len(ids) == 1 and sum(isinstance(r, CaseError) for r in results) == 11
            )
            assert (await history(contexts[1], -100))[0]["action"] == "tban:pending"
            assert not await history(contexts[0], -200)
            assert not await history(contexts[2], -100)
            await begin(contexts[2], -100, 1, 11, 22, "tban", 3600, "clone")
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_case_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_case_update BEFORE UPDATE ON agent_restriction_cases FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_case_update()"""
                )
                try:
                    with pytest.raises(CaseError):
                        await finish(contexts[0], ids[0], "applied")
                    assert (await history(contexts[1], -100))[0][
                        "action"
                    ] == "tban:pending"
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_case_update ON agent_restriction_cases"
                    )
            await finish(contexts[0], ids[0], "applied")
            assert (await history(contexts[1], -100))[0]["action"] == "tban:applied"
            with pytest.raises(CaseError):
                await finish(contexts[1], ids[0], "partial")
            with pytest.raises(CaseError):
                await finish(contexts[2], ids[0], "applied")
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_restriction_cases WHERE tenant=$1",
                            db.scope,
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_applied_action_with_failed_outcome_write_is_not_reported_as_unattempted(
    tmp_path, monkeypatch
):
    from agent.modules.moderation import restrictions
    from agent.platform.restriction_cases import CaseError

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        monkeypatch.setattr(
            restrictions, "finish", AsyncMock(side_effect=CaseError("offline"))
        )
        message = fixtures.FakeMessage("/tban 22 1h")
        client = client_with_rights()
        await commands["tban"](client, message)
        client.ban_chat_member.assert_awaited_once()
        assert (
            "banned" in message.replies[-1]
            and "Audit outcome could not be recorded" in message.replies[-1]
        )

    asyncio.run(scenario())


def test_username_target_failures_are_safe_before_restriction(tmp_path, caplog):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        commands = moderation.build(ctx)[1]
        for error in (ValueError('SECRET_PROVIDER_TEXT'), RuntimeError('SECRET_PROVIDER_TEXT')):
            client = client_with_rights()
            client.get_users = AsyncMock(side_effect=error)
            message = fixtures.FakeMessage('/tban @target 1h')
            await commands['tban'](client, message)
            client.ban_chat_member.assert_not_awaited()
            assert 'SECRET_PROVIDER_TEXT' not in str(message.replies) + caplog.text
            assert 'lookup unavailable' in str(message.replies).lower()
    asyncio.run(scenario())


def test_username_target_rejects_nonpersonal_lookup_results():
    import pytest
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        for uid in (None, True, '22', 0, -22, 2**63):
            client = SimpleNamespace(get_users=AsyncMock(return_value=SimpleNamespace(id=uid)))
            with pytest.raises(ValueError, match='lookup unavailable'):
                await target_and_reason(client, fixtures.FakeMessage('/tban @target 1h'))
    asyncio.run(scenario())


def test_username_target_lookup_has_a_deadline_and_cleans_up(monkeypatch):
    import pytest
    from agent.modules.moderation import restrictions
    async def scenario():
        stopped = asyncio.Event()
        async def blocked(*args):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        client = SimpleNamespace(get_users=AsyncMock(side_effect=blocked))
        original = asyncio.wait_for
        async def fast_timeout(awaitable, timeout):
            assert timeout == 5
            return await original(awaitable, timeout=0.01)
        monkeypatch.setattr(asyncio, 'wait_for', fast_timeout)
        # Outer watchdog makes the pre-fix failure terminate without hanging.
        with pytest.raises(ValueError, match='lookup unavailable'):
            await original(restrictions.target_and_reason(client, fixtures.FakeMessage('/tban @target 1h')), timeout=0.2)
        assert stopped.is_set()
    asyncio.run(scenario())


def test_username_target_cancellation_propagates_without_retry():
    import pytest
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        reached = asyncio.Event()
        stopped = asyncio.Event()
        async def blocked(*args):
            reached.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        client = SimpleNamespace(get_users=AsyncMock(side_effect=blocked))
        task = asyncio.create_task(target_and_reason(client, fixtures.FakeMessage('/tban @target 1h')))
        await asyncio.wait_for(reached.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
        client.get_users.assert_awaited_once_with('@target')
    asyncio.run(scenario())


def test_moderation_mention_spans_reject_malformed_target_without_lookup():
    import pytest
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        for length in (None, True, 0, -1, '6', 1, 999, 3):
            # Length 1 splits the emoji; length 3 stops inside the visible name.
            message = fixtures.FakeMessage('/tban 😀Alice 1h reason')
            message.entities = [SimpleNamespace(offset=6, length=length, user=SimpleNamespace(id=22))]
            client = SimpleNamespace(get_users=AsyncMock())
            with pytest.raises(ValueError, match='mention'):
                await target_and_reason(client, message)
            client.get_users.assert_not_awaited()
        message.entities = [SimpleNamespace(offset=6, length=7, user=SimpleNamespace(id=22))] * 2
        with pytest.raises(ValueError, match='mention'):
            await target_and_reason(client, message)
    asyncio.run(scenario())


def test_moderation_mention_preserves_reason_and_its_other_mentions():
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        label = '😀 Alice Smith'
        prefix = '/tban@MeikoBot  '
        reason = '1h reported by Other Member'
        message = fixtures.FakeMessage(prefix + label + ' ' + reason)
        message.entities = [SimpleNamespace(offset=len(prefix),
            length=len(label.encode('utf-16-le')) // 2, user=SimpleNamespace(id=22)),
            SimpleNamespace(offset=len((prefix + label + ' 1h reported by ').encode('utf-16-le')) // 2,
                            length=12, user=SimpleNamespace(id=33))]
        client = SimpleNamespace(get_users=AsyncMock())
        assert await target_and_reason(client, message) == (22, reason)
        client.get_users.assert_not_awaited()
    asyncio.run(scenario())


def test_moderation_mention_target_offset_uses_argument_not_command_substring():
    from agent.modules.moderation.restrictions import target_and_reason
    async def scenario():
        message = fixtures.FakeMessage('/tban ban')
        message.entities = [SimpleNamespace(offset=6, length=3, user=SimpleNamespace(id=22))]
        client = SimpleNamespace(get_users=AsyncMock())
        assert await target_and_reason(client, message) == (22, '')
        client.get_users.assert_not_awaited()
    asyncio.run(scenario())
