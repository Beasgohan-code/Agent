"""Explicit approval commands replace the old toggling command."""

import asyncio
import test_moderation as fixtures
from agent.modules import moderation


def test_approval_commands_are_explicit_and_idempotent(tmp_path):
    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        _, commands = moderation.build(ctx)
        assert "trust" not in commands
        assert {"approve", "unapprove", "approval", "approved"} <= commands.keys()
        client = fixtures.FakeClient()
        for _ in range(2):
            await commands["approve"](
                client, fixtures.FakeMessage("/approve", reply=True)
            )
            assert ctx.chats.is_trusted(-100500, 22)
        query = fixtures.FakeMessage("/approval 22")
        await commands["approval"](client, query)
        assert "approved" in query.replies[-1].lower()
        listing = fixtures.FakeMessage("/approved")
        await commands["approved"](client, listing)
        assert "22" in listing.replies[-1]
        for _ in range(2):
            await commands["unapprove"](client, fixtures.FakeMessage("/unapprove 22"))
            assert not ctx.chats.is_trusted(-100500, 22)

    asyncio.run(scenario())


def test_approval_permissions_invalid_targets_and_pagination(tmp_path):
    from dataclasses import replace

    async def scenario():
        ctx = fixtures.ctx.__wrapped__(tmp_path)
        ctx.settings = replace(ctx.settings, owner_id=11)
        _, commands = moderation.build(ctx)
        for name in ("approve", "unapprove", "approval", "approved"):
            request = fixtures.FakeMessage("/" + name + " 22")
            await commands[name](fixtures.FakeClient(caller=fixtures.MEMBER), request)
            assert not ctx.chats.is_trusted(-100500, 22)
        for text in ("/approve -1", "/approve 0", "/approve 22 extra", "/approve nope"):
            request = fixtures.FakeMessage(text)
            await commands["approve"](fixtures.FakeClient(), request)
            assert not ctx.chats.is_trusted(-100500, 22)
        for i in range(45):
            ctx.chats.toggle_trust(-100500, 1000 + i)
        request = fixtures.FakeMessage("/approved 3")
        await commands["approved"](fixtures.FakeClient(), request)
        assert "1044" in request.replies[-1] and "1000" not in request.replies[-1]
        for text in ("/approved 0", "/approved ١", "/approved 2 extra"):
            request = fixtures.FakeMessage(text)
            await commands["approved"](fixtures.FakeClient(), request)
            assert "Usage" in request.replies[-1]

    asyncio.run(scenario())
