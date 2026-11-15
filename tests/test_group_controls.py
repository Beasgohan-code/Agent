"""Group controls authorize the presser and use canonical greeting services."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.modules import group
from agent.platform.actions import ActionRouter
import test_group as fixtures


def context(tmp_path):
    ctx = fixtures.ctx.__wrapped__(tmp_path)
    ctx.actions = ActionRouter()
    return ctx


def query(data, uid=11):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=uid),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        message=SimpleNamespace(chat=fixtures.FakeChat()),
    )


def test_settings_reads_canonical_greetings_not_stale_document(tmp_path, monkeypatch):
    async def scenario():
        ctx = context(tmp_path)
        ctx.chats.set_greeting(fixtures.CHAT, "welcome", "legacy")
        reader = AsyncMock(return_value={"enabled": False, "text": "canonical"})
        monkeypatch.setattr("agent.modules.welcome.read_greeting", reader)
        _, handlers = group.build(ctx)
        message = fixtures.FakeMessage("/settings")
        await handlers["settings"](fixtures.FakeClient(), message)
        assert reader.await_count == 2

    asyncio.run(scenario())


def test_nonadmin_cannot_toggle_or_read_greeting(tmp_path, monkeypatch):
    async def scenario():
        ctx = context(tmp_path)
        reader, writer = AsyncMock(), AsyncMock()
        monkeypatch.setattr("agent.modules.welcome.read_greeting", reader)
        monkeypatch.setattr("agent.modules.welcome.toggle_greeting", writer)
        group.build(ctx)
        press = query("gmanage:welcome:off")
        await ctx.actions.dispatch(fixtures.FakeClient(caller=fixtures.MEMBER), press)
        reader.assert_not_awaited()
        writer.assert_not_awaited()
        assert press.answer.await_args.kwargs["show_alert"]

    asyncio.run(scenario())


def test_authorized_toggle_preserves_template_and_targets_current_group(
    tmp_path, monkeypatch
):
    async def scenario():
        ctx = context(tmp_path)
        ctx.chats.set_greeting(fixtures.CHAT, "welcome", "Hello {name}")
        monkeypatch.setattr("agent.modules.group.controls.edit", AsyncMock())
        group.build(ctx)
        press = query("gmanage:welcome:off")
        await ctx.actions.dispatch(fixtures.FakeClient(), press)
        state = ctx.chats.greeting(fixtures.CHAT, "welcome")
        assert state == {"text": "Hello {name}", "enabled": False}
        assert not ctx.chats.greeting(-123, "welcome")["text"]

    asyncio.run(scenario())


def test_failed_toggle_does_not_claim_success(tmp_path, monkeypatch):
    async def scenario():
        ctx = context(tmp_path)
        monkeypatch.setattr(
            "agent.modules.welcome.toggle_greeting",
            AsyncMock(side_effect=RuntimeError("secret db url")),
        )
        group.build(ctx)
        press = query("gmanage:welcome:off")
        await ctx.actions.dispatch(fixtures.FakeClient(), press)
        text = press.answer.await_args.args[0]
        assert "not confirmed" in text
        assert "secret" not in text

    asyncio.run(scenario())


def test_empty_greeting_cannot_be_enabled_from_panel(tmp_path):
    async def scenario():
        ctx = context(tmp_path)
        group.build(ctx)
        press = query("gmanage:welcome:on")
        await ctx.actions.dispatch(fixtures.FakeClient(), press)
        assert "Add a message" in press.answer.await_args.args[0]
        assert not press.edit_message_text.await_count

    asyncio.run(scenario())


def test_group_settings_do_not_trust_deployment_owner_over_group_rights(tmp_path):
    from dataclasses import replace

    async def scenario():
        ctx = context(tmp_path)
        ctx.settings = replace(ctx.settings, owner_id=11)
        _, commands = group.build(ctx)
        message = fixtures.FakeMessage("/setrules changed")
        await commands["setrules"](fixtures.FakeClient(caller=fixtures.MEMBER), message)
        assert not ctx.chats.get(fixtures.CHAT, "rules", "")
        assert message.replies == [group.DENIED]

    asyncio.run(scenario())


def test_settings_outage_does_not_display_stale_greetings(tmp_path):
    async def scenario():
        ctx = context(tmp_path)
        ctx.chats.set_greeting(fixtures.CHAT, "welcome", "stale")
        ctx.db = SimpleNamespace(connected=False, _pool=None)
        _, commands = group.build(ctx)
        message = fixtures.FakeMessage("/settings")
        await commands["settings"](fixtures.FakeClient(), message)
        assert "could not be loaded" in message.replies[0]
        assert "stale" not in message.replies[0]

    asyncio.run(scenario())


import os
import uuid
import pytest
from agent.platform.db import Database
from agent.platform.greetings import Greetings


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="PostgreSQL required"
)
def test_controls_use_confirmed_sql_and_preserve_canonical_text(tmp_path, monkeypatch):
    async def scenario():
        db = Database(
            os.environ["AGENT_TEST_DATABASE_URL"],
            scope="gcontrols:" + uuid.uuid4().hex,
            required=True,
        )
        try:
            assert await db.connect()
            ctx = context(tmp_path)
            ctx.chats.set_greeting(fixtures.CHAT, "welcome", "old cached text")
            ctx.db = db
            service = Greetings(db)
            await service.set(fixtures.CHAT, "welcome", "canonical message")
            editor = AsyncMock()
            monkeypatch.setattr("agent.modules.group.controls.edit", editor)
            group.build(ctx)
            press = query("gmanage:welcome:off")
            await ctx.actions.dispatch(fixtures.FakeClient(), press)
            assert await service.get(fixtures.CHAT, "welcome", {}) == {
                "text": "canonical message",
                "enabled": False,
            }
            assert "canonical message" in str(editor.await_args.args[1])
            assert "old cached text" not in str(editor.await_args.args[1])
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_greetings WHERE tenant=$1", db.scope
                    )
            await db.close()

    asyncio.run(scenario())
