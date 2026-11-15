"""Blocklists use bounded glob matching, not raw regular expressions."""

import asyncio
import test_moderation as fixtures
from agent.modules import moderation


def test_blocklist_commands_register_and_store_quoted_phrase(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert {
            "addblocklist",
            "rmblocklist",
            "unblocklistall",
            "blocklist",
            "blocklistmode",
            "blocklistdelete",
            "setblocklistreason",
            "resetblocklistreason",
        } <= commands.keys()
        await commands["addblocklist"](
            admin_client(),
            fixtures.FakeMessage('/addblocklist "bad phrase" Please stop'),
        )
        message = fixtures.FakeMessage("/blocklist")
        await commands["blocklist"](admin_client(), message)
        assert "bad phrase" in message.replies[-1]

    asyncio.run(scenario())


def admin_client():
    client = fixtures.FakeClient()

    async def member(chat, user):
        status = fixtures.ADMIN if user == 11 else fixtures.MEMBER
        result = fixtures.member(status)
        result.privileges.can_change_info = True
        return result

    client.get_chat_member = member
    return client


def test_safe_matching_boundaries_normalization_and_wildcards():
    from agent.platform.blocklists import (
        matches,
        trigger,
        find_match,
        DEFAULT,
        BlocklistError,
    )
    from types import SimpleNamespace
    import pytest

    assert matches("hi", "hi, there") and not matches("hi", "this")
    assert matches("hi there", "hî   thérê")
    assert matches("bit?", "bite") and not matches("bit?", "bit")
    assert matches("hi * you", "hi there you") and not matches(
        "hi * you", "hi there dear you"
    )
    assert matches("hi ** you", "hi there dear you")
    assert matches("*hi*", "this")
    assert matches(r"\*", "a * b") and not matches(r"\*", "plain")
    assert matches("😀", "hi😀there")
    assert matches("*.pdf", "Document.PDF", filename=True)
    assert not matches("report.pdf", "a-report.pdf.exe", filename=True)
    assert not matches("a*" * 60 + "z", "a" * 8192)
    for pattern in ("*", "**", "?", "a\\", "inline:test", ""):
        with pytest.raises(BlocklistError):
            trigger(pattern)
    policy = {
        **DEFAULT,
        "entries": [
            {"trigger": "file:*.exe", "reason": "unsafe file"},
            {"trigger": "bad phrase", "reason": "text"},
        ],
    }
    assert (
        find_match(
            policy, SimpleNamespace(document=SimpleNamespace(file_name="evil.exe"))
        )["reason"]
        == "unsafe file"
    )
    assert find_match(policy, SimpleNamespace(caption="Bad phrase"))["reason"] == "text"


def test_glob_nfa_matches_small_reference_language():
    import itertools
    import re
    from agent.platform.blocklists import matches

    for parts in itertools.product(("a", "b", "*", "?", " "), repeat=3):
        pattern = "".join(parts).strip()
        if not any(c in "ab" for c in pattern):
            continue
        # Collapse consecutive stars the same way as the production glob grammar.
        tokens = re.findall(r"\*+|\?|.", pattern)
        expression = "".join(
            ".*"
            if len(t) > 1 and t[0] == "*"
            else r"\S*"
            if t == "*"
            else r"\S"
            if t == "?"
            else re.escape(t)
            for t in tokens
        )
        if pattern[0].isalnum():
            expression = r"(?<!\w)" + expression
        if pattern[-1].isalnum():
            expression += r"(?!\w)"
        for text in ("a", "b", "ab", "a b", "aa b a", "bbb", "a a a"):
            assert matches(pattern, text) == bool(re.search(expression, text)), (
                pattern,
                text,
            )


def test_blocklist_watcher_actions_exemptions_and_cleanup(tmp_path):
    from agent.modules.moderation.blocklists import enforce
    from agent.platform.blocklists import operate
    from unittest.mock import AsyncMock

    async def scenario():
        for mode in ("nothing", "warn", "ban", "mute", "kick", "tban", "tmute"):
            ctx = fixtures.ctx.__wrapped__(tmp_path / mode)
            await operate(ctx, -100500, "add", ("bad phrase", "Please stop"), actor=11)
            await operate(
                ctx,
                -100500,
                "mode",
                (mode, 3600 if mode.startswith("t") else 0),
                actor=11,
            )
            client = admin_client()
            client.ban_chat_member = AsyncMock(return_value=True)
            client.unban_chat_member = AsyncMock(return_value=True)
            client.restrict_chat_member = AsyncMock(return_value=True)
            client.delete_messages = AsyncMock(return_value=True)
            message = fixtures.FakeMessage("bad phrase", uid=22)
            assert await enforce(ctx, client, message)
            client.delete_messages.assert_awaited_once_with(-100500, 100)
            if mode in ("ban", "tban", "kick"):
                client.ban_chat_member.assert_awaited_once()
            elif mode in ("mute", "tmute"):
                client.restrict_chat_member.assert_awaited_once()
            elif mode == "warn":
                assert ctx.chats.active_warning_count(-100500, 22) == 1
            ctx.chats.toggle_trust(-100500, 22)
            client.delete_messages.reset_mock()
            assert not await enforce(ctx, client, message)
            client.delete_messages.assert_not_awaited()
            assert not await enforce(
                ctx, client, fixtures.FakeMessage("bad phrase", uid=11)
            )

    asyncio.run(scenario())


def test_blocklist_delete_off_and_owner_confirmation(tmp_path):
    from agent.platform.blocklists import operate, BlocklistError
    from agent.modules.moderation.blocklists import enforce
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import pytest

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        await operate(ctx, -100500, "add", ("bad", "reason"), actor=11)
        await operate(ctx, -100500, "delete", False, actor=11)
        client = admin_client()
        client.delete_messages = AsyncMock()
        assert not await enforce(ctx, client, fixtures.FakeMessage("bad", uid=22))
        client.delete_messages.assert_not_awaited()
        _, commands = moderation.build(ctx)
        request = fixtures.FakeMessage("/unblocklistall confirm")
        await commands["unblocklistall"](client, request)
        assert (await operate(ctx, -100500))["entries"]
        with pytest.raises(BlocklistError):
            await operate(ctx, -100500, "clear", actor=11, client=client)
        client.get_chat_member = AsyncMock(
            return_value=SimpleNamespace(status=fixtures.OWNER)
        )
        request = fixtures.FakeMessage("/unblocklistall")
        await commands["unblocklistall"](client, request)
        assert (await operate(ctx, -100500))["entries"]
        await commands["unblocklistall"](
            client, fixtures.FakeMessage("/unblocklistall confirm")
        )
        assert not (await operate(ctx, -100500))["entries"]

    asyncio.run(scenario())


def test_outage_and_nonadmin_commands_never_confirm_or_mutate(tmp_path):
    from types import SimpleNamespace
    from agent.platform.blocklists import operate
    from agent.modules.moderation.blocklists import enforce
    from unittest.mock import AsyncMock

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        for command in ("addblocklist", "blocklistmode", "unblocklistall"):
            await commands[command](
                client, fixtures.FakeMessage("/" + command + " ban")
            )
        assert not (await operate(ctx, -100500))["entries"]
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        request = fixtures.FakeMessage("/addblocklist bad reason")
        await commands["addblocklist"](admin_client(), request)
        assert "unavailable" in request.replies[-1]
        client = admin_client()
        client.ban_chat_member = AsyncMock()
        client.delete_messages = AsyncMock()
        assert not await enforce(ctx, client, fixtures.FakeMessage("bad", uid=22))
        client.ban_chat_member.assert_not_awaited()
        client.delete_messages.assert_not_awaited()

    asyncio.run(scenario())


def test_pg_shared_policy_limits_audit_rollback_and_action_replay(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.blocklists import operate, event, history, BlocklistError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        scope = "blocklist-test:" + uuid.uuid4().hex
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
            for i in range(99):
                await operate(
                    contexts[0], -100, "add", (f"trigger{i}", "reason"), actor=11
                )
            results = await asyncio.gather(
                *(
                    operate(
                        contexts[i % 2],
                        -100,
                        "add",
                        (f"new{i}", "reason"),
                        actor=11 + i,
                    )
                    for i in range(12)
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(r, dict) for r in results) == 1
            assert sum(isinstance(r, BlocklistError) for r in results) == 11
            assert len((await operate(contexts[1], -100))["entries"]) == 100
            assert not (await operate(contexts[2], -100))["entries"]
            assert not (await operate(contexts[0], -200))["entries"]
            await asyncio.gather(
                operate(contexts[0], -100, "mode", ("tban", 3600), actor=11),
                operate(contexts[1], -100, "delete", False, actor=22),
            )
            policy = await operate(contexts[0], -100)
            assert policy["mode"] == "tban" and not policy["delete"]
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    """CREATE OR REPLACE FUNCTION pg_temp.reject_blocklist_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'reject'; END $$"""
                )
                await conn.execute(
                    f"""CREATE TRIGGER reject_blocklist_audit BEFORE INSERT ON agent_blocklist_revisions FOR EACH ROW WHEN (NEW.tenant='{scope}') EXECUTE FUNCTION pg_temp.reject_blocklist_audit()"""
                )
                try:
                    with pytest.raises(BlocklistError):
                        await operate(contexts[0], -100, "remove", "trigger0", actor=11)
                    assert await operate(contexts[1], -100) == policy
                finally:
                    await conn.execute(
                        "DROP TRIGGER reject_blocklist_audit ON agent_blocklist_revisions"
                    )
            results = await asyncio.gather(
                *(
                    event(contexts[i % 2], -100, 1, 22, "tban", "reason")
                    for i in range(12)
                )
            )
            assert sum(results) == 1
            assert (await history(contexts[0], -100))[0][
                "action"
            ] == "blocklist:tban:pending"
            assert not await history(contexts[2], -100)
            assert not await history(contexts[1], -200)
            assert await event(contexts[2], -100, 1, 22, "tban", "reason")
            assert await event(
                contexts[1], -100, 1, 22, "tban", "reason", outcome="applied"
            )
            assert not await event(
                contexts[0], -100, 1, 22, "tban", "reason", outcome="partial"
            )
            assert (await history(contexts[0], -100))[0][
                "action"
            ] == "blocklist:tban:applied"
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_blocklist_actions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_blocklist_revisions WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_blocklists WHERE tenant=$1", db.scope
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_blocklist_card_authorizes_presser_before_reading(tmp_path, monkeypatch):
    import test_group_controls as controls
    import test_group as group_fixtures
    from agent.modules import group
    from unittest.mock import AsyncMock

    async def scenario():
        ctx = controls.context(tmp_path)
        reader = AsyncMock(
            return_value={
                "entries": [],
                "mode": "nothing",
                "seconds": 0,
                "delete": True,
            }
        )
        editor = AsyncMock()
        monkeypatch.setattr("agent.modules.group.controls.read_blocklist", reader)
        monkeypatch.setattr("agent.modules.group.controls.edit", editor)
        group.build(ctx)
        request = controls.query("gmanage:blocklist:show")
        await ctx.actions.dispatch(
            group_fixtures.FakeClient(caller=group_fixtures.MEMBER), request
        )
        reader.assert_not_awaited()
        editor.assert_not_awaited()
        await ctx.actions.dispatch(group_fixtures.FakeClient(), request)
        reader.assert_awaited_once_with(ctx, group_fixtures.CHAT)
        assert "Blocklist settings" in str(editor.await_args.args[1])

    asyncio.run(scenario())


def test_advanced_selectors_anchor_and_isolate_surfaces():
    from types import SimpleNamespace as NS
    from agent.platform.blocklists import trigger, find_match

    def hit(pattern, **fields):
        policy = {"entries": [{"trigger": trigger(pattern), "reason": "matched"}]}
        return find_match(policy, NS(**fields)) is not None

    assert hit("prefix:buy", text="BUY now")
    assert not hit("prefix:buy", text="please buy now")
    assert not hit("prefix:buy", text="buyer")
    assert hit("prefix:buy*", caption="buyer")
    assert hit("exact:buy now", text="Búy   now")
    assert not hit("exact:buy now", text="buy now please")
    assert hit("exact:buy **", text="buy something now")
    assert hit(
        "name:scam*",
        from_user=NS(first_name="Scámmer", last_name="Jones"),
        text="hello",
    )
    assert not hit("name:scam*", from_user=NS(first_name="Normal"), text="scammer")
    assert hit("username:spam*", from_user=NS(username="Spam123"))
    assert not hit("username:spam", from_user=NS(username="spammer"))
    assert not hit("username:spam*", sender_chat=NS(username="spam123"))
    assert not hit("prefix:hello", document=NS(file_name="hello.txt"))
    assert not hit("exact:hello", text="x" * 8193)


def test_meiko_display_name_preserves_plugin_identity():
    from agent.ui.screens import welcome_screen, HELP_SECTIONS
    from agent.ui.theme import Theme
    from types import SimpleNamespace

    screen = welcome_screen(SimpleNamespace(first_name="Tester", last_name=""), Theme())
    assert "Meiko" in screen.rich_text
    assert any("AI Agent" in row for row in HELP_SECTIONS)


def test_bulk_triggers_share_reason_and_rollback_on_invalid_or_full(tmp_path):
    from agent.platform.blocklists import operate

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, handlers = moderation.build(ctx)
        client = admin_client()
        for prefix in "/!.?":
            await handlers["addblocklist"](
                client,
                fixtures.FakeMessage(
                    prefix
                    + 'addblocklist ("bad phrase" file:*.exe "prefix:buy now") No advertising'
                ),
            )
            state = await operate(ctx, -100500)
            assert len(state["entries"]) == 3
            assert {entry["reason"] for entry in state["entries"]} == {"No advertising"}
        await handlers["addblocklist"](
            client, fixtures.FakeMessage("!addblocklist (valid **) Nope")
        )
        assert await operate(ctx, -100500) == state
        await handlers["rmblocklist"](
            client, fixtures.FakeMessage('?rmblocklist ("bad phrase" file:*.exe)')
        )
        assert [e["trigger"] for e in (await operate(ctx, -100500))["entries"]] == [
            "prefix:buy now"
        ]
        for i in range(98):
            await operate(ctx, -100500, "add", (f"word{i}", ""), actor=11)
        before = await operate(ctx, -100500)
        await handlers["addblocklist"](
            client, fixtures.FakeMessage(".addblocklist (first second) reason")
        )
        assert await operate(ctx, -100500) == before

    asyncio.run(scenario())


def test_bulk_parser_preserves_escapes_and_refuses_ambiguous_input():
    import pytest
    from agent.modules.moderation.blocklists import parse_triggers

    assert parse_triggers('(one "two words" file:*.exe) shared reason') == (
        ["one", "two words", "file:*.exe"],
        "shared reason",
    )
    assert parse_triggers(r'("a)b" literal\*) why') == (["a)b", r"literal\*"], "why")
    for value in (
        "()",
        "(one",
        "(one)reason",
        "(one (two))",
        '("unclosed)',
        "(" + " ".join("x" + str(i) for i in range(21)) + ")",
    ):
        with pytest.raises(ValueError):
            parse_triggers(value)


def test_pg_bulk_edits_are_single_revision_and_concurrent_quota_atomic(tmp_path):
    import os
    import uuid
    import pytest
    from agent.platform.db import Database
    from agent.platform.blocklists import operate, BlocklistError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="bulk:" + uuid.uuid4().hex,
            required=True,
        )
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.db = db
        try:
            assert await db.connect()
            await operate(
                ctx,
                -100,
                "add_many",
                [("word" + str(i), "") for i in range(20)],
                actor=11,
            )
            async with db._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_blocklist_revisions WHERE tenant=$1",
                        db.scope,
                    )
                    == 1
                )
            before = await operate(ctx, -100)
            for op, values in (
                ("add_many", [("valid", ""), ("**", "")]),
                ("remove_many", ["word0", "**"]),
            ):
                with pytest.raises(BlocklistError):
                    await operate(ctx, -100, op, values, actor=11)
                assert await operate(ctx, -100) == before
            for start in (20, 40, 60):
                await operate(
                    ctx,
                    -100,
                    "add_many",
                    [("word" + str(i), "") for i in range(start, start + 20)],
                    actor=11,
                )
            results = await asyncio.gather(
                *(
                    operate(
                        ctx,
                        -100,
                        "add_many",
                        [(f"batch{j}word{i}", "") for i in range(15)],
                        actor=11,
                    )
                    for j in range(4)
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(r, dict) for r in results) == 1
            assert sum(isinstance(r, BlocklistError) for r in results) == 3
            assert len((await operate(ctx, -100))["entries"]) == 95
            assert not (await operate(ctx, -200))["entries"]
            async with db._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM agent_blocklist_revisions WHERE tenant=$1",
                        db.scope,
                    )
                    == 5
                )
            await operate(ctx, -100, "remove_many", ["word0", "word1"], actor=11)
            assert len((await operate(ctx, -100))["entries"]) == 93
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_blocklist_revisions WHERE tenant=$1",
                        db.scope,
                    )
                    await conn.execute(
                        "DELETE FROM agent_blocklists WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())
