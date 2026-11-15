"""Consecutive and timed antiflood are separate, explicit policies."""

import asyncio
import test_moderation as fixtures
from agent.modules import moderation


def test_antiflood_commands_and_persisted_modes(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert {
            "flood",
            "setflood",
            "setfloodtimer",
            "floodmode",
            "clearflood",
        } <= commands.keys()
        for command, text in [
            ("setflood", "/setflood 7"),
            ("setfloodtimer", "/setfloodtimer 10 30s"),
            ("floodmode", "/floodmode tban 3d"),
            ("clearflood", "/clearflood off"),
        ]:
            await commands[command](fixtures.FakeClient(), fixtures.FakeMessage(text))
        policy = ctx.chats.antispam(-100500)
        assert policy["consecutive_limit"] == 7
        assert policy["timed_flood_count"] == 10 and policy["timed_flood_seconds"] == 30
        assert (
            policy["flood_action"] == "tban"
            and policy["flood_action_seconds"] == 259200
        )
        assert policy["clear_flood"] is False

    asyncio.run(scenario())


def test_consecutive_timed_resets_and_group_isolation():
    from agent.modules.moderation.antiflood import Counter

    counter = Counter()
    policy = {"consecutive_limit": 3, "timed_flood_count": 0}
    assert not counter.note(-1, 1, 1, policy, 0)
    assert not counter.note(-1, 1, 2, policy, 1)
    assert not counter.note(-1, 2, 3, policy, 2)
    assert not counter.note(-1, 1, 4, policy, 3)
    assert not counter.note(-2, 1, 5, policy, 4)
    assert not counter.note(-1, 1, 6, policy, 5)
    assert counter.note(-1, 1, 7, policy, 6) == [4, 6, 7]
    policy = {"consecutive_limit": 0, "timed_flood_count": 3, "timed_flood_seconds": 30}
    assert not counter.note(-1, 1, 8, policy, 0)
    assert not counter.note(-1, 2, 9, policy, 1)
    assert not counter.note(-1, 1, 10, policy, 20)
    assert counter.note(-1, 1, 11, policy, 30) == [8, 10, 11]
    counter.clear(-1, 1)
    assert not counter.note(-1, 1, 12, policy, 31)
    assert not counter.note(-1, 1, 13, policy, 62)


def test_watcher_temporary_ban_cleanup_and_approval(tmp_path):
    from agent.modules.moderation.antiflood import watch
    from unittest.mock import AsyncMock

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        for command, text in [
            ("setflood", "/setflood 2"),
            ("floodmode", "/floodmode tban 3d"),
        ]:
            await commands[command](fixtures.FakeClient(), fixtures.FakeMessage(text))
        client = fixtures.FakeClient(caller=fixtures.MEMBER)
        client.ban_chat_member = AsyncMock(return_value=True)
        client.delete_messages = AsyncMock(return_value=True)
        watcher = watch(ctx)
        for i in (1, 2):
            await watcher(client, fixtures.FakeMessage("message", uid=22, message_id=i))
        client.ban_chat_member.assert_awaited_once()
        assert "until_date" in client.ban_chat_member.await_args.kwargs
        assert client.delete_messages.await_args.args == (-100500, [1, 2])
        ctx.chats.toggle_trust(-100500, 22)
        client.ban_chat_member.reset_mock()
        for i in (3, 4):
            await watcher(client, fixtures.FakeMessage("message", uid=22, message_id=i))
        client.ban_chat_member.assert_not_awaited()

    asyncio.run(scenario())


def test_invalid_inputs_and_outage_do_not_confirm_changes(tmp_path):
    from types import SimpleNamespace

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        for command, text in [
            ("setflood", "/setflood 1"),
            ("setfloodtimer", "/setfloodtimer 10 2d"),
            ("floodmode", "/floodmode tban"),
            ("floodmode", "/floodmode ban 3d"),
        ]:
            message = fixtures.FakeMessage(text)
            await commands[command](fixtures.FakeClient(), message)
            assert not ctx.chats.antispam(-100500).get("consecutive_limit")
            assert "Antiflood</b>" not in message.replies[-1]
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        message = fixtures.FakeMessage("/setflood 7")
        await commands["setflood"](fixtures.FakeClient(), message)
        assert "unavailable" in message.replies[-1]

    asyncio.run(scenario())


def test_all_actions_and_cleanup_off(tmp_path):
    from agent.modules.moderation.antiflood import watch
    from unittest.mock import AsyncMock

    async def scenario():
        for mode in ("ban", "mute", "kick", "tban", "tmute"):
            ctx = fixtures.ctx.__wrapped__(tmp_path / mode)
            _, commands = moderation.build(ctx)
            for command, text in [
                ("setflood", "/setflood 2"),
                ("clearflood", "/clearflood off"),
                (
                    "floodmode",
                    "/floodmode " + mode + (" 5w" if mode.startswith("t") else ""),
                ),
            ]:
                await commands[command](
                    fixtures.FakeClient(), fixtures.FakeMessage(text)
                )
            client = fixtures.FakeClient(caller=fixtures.MEMBER)
            client.ban_chat_member = AsyncMock(return_value=True)
            client.unban_chat_member = AsyncMock(return_value=True)
            client.restrict_chat_member = AsyncMock(return_value=True)
            client.delete_messages = AsyncMock(return_value=True)
            watcher = watch(ctx)
            await asyncio.gather(
                *(
                    watcher(
                        client, fixtures.FakeMessage("message", uid=22, message_id=i)
                    )
                    for i in (1, 2)
                )
            )
            client.delete_messages.assert_not_awaited()
            method = (
                client.restrict_chat_member
                if mode in ("mute", "tmute")
                else client.ban_chat_member
            )
            method.assert_awaited_once()
            assert ("until_date" in method.await_args.kwargs) == mode.startswith("t")
            assert client.unban_chat_member.await_count == (1 if mode == "kick" else 0)

    asyncio.run(scenario())
