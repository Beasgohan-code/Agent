"""Policy regression tests; injected clients do not prove live Telegram playback."""

import asyncio

import pytest

from test_clone import build, FakeMessage, FakePremium, TOKEN_A, MEMBER, OWNER, run
from agent.modules.clone.store import Clone
from agent.modules.clone.manager import CloneError


@pytest.mark.parametrize("user_id", [OWNER, MEMBER])
def test_owner_and_sudo_cannot_create_without_premium(tmp_path, user_id):
    ctx, _, commands = build(tmp_path, premium=FakePremium())
    ctx.sudo.change(OWNER, MEMBER, add=True)
    message = FakeMessage("/clone " + TOKEN_A, uid=user_id)
    run(commands["clone"], ctx, message)
    assert not ctx.clones.current()
    assert "requires bot premium" in message.replies[0]


@pytest.mark.parametrize("user_id", [OWNER, MEMBER])
def test_owner_and_sudo_cannot_start_stored_clone_without_premium(tmp_path, user_id):
    ctx, _, _ = build(tmp_path, premium=FakePremium())
    ctx.sudo.change(OWNER, MEMBER, add=True)
    record = Clone(bot_id=111111111, token=TOKEN_A, owner_id=user_id)
    with pytest.raises(CloneError, match="premium"):
        asyncio.run(ctx.clones.start(record))
    assert not ctx.clones.is_running(record.bot_id)


def test_premium_revocation_blocks_restart_even_for_owner(tmp_path):
    premium = FakePremium({OWNER})
    ctx, _, commands = build(tmp_path, premium=premium)
    run(commands["clone"], ctx, FakeMessage("/clone " + TOKEN_A, uid=OWNER))
    record = ctx.clones.current()[0]
    asyncio.run(ctx.clones.stop(record.bot_id))
    premium.ids.clear()
    with pytest.raises(CloneError, match="premium"):
        asyncio.run(ctx.clones.start(record))


@pytest.mark.parametrize("user_id", [OWNER, MEMBER])
def test_expired_premium_blocks_callbacks_recovery_and_restart(tmp_path, user_id):
    from test_clone import FakeQuery

    async def scenario():
        premium = FakePremium({user_id})
        ctx, _, commands = build(tmp_path, premium=premium)
        ctx.sudo.change(OWNER, MEMBER, add=True)
        await commands["clone"](
            None, FakeMessage("/clone " + TOKEN_A + " files", uid=user_id)
        )
        premium.ids.clear()
        await ctx.clones.stop(111111111)
        assert await ctx.clones.restore() == ()
        with pytest.raises(CloneError, match="premium"):
            await ctx.clones.restart(ctx.clones.record(111111111))
        for action in ("start", "profile", "p:tiny"):
            press = FakeQuery("clone:111111111:" + action, uid=user_id)
            await ctx.actions.dispatch(None, press)
            assert "premium" in press.answers[-1][0].lower()
            assert not ctx.clones.is_running(111111111)
        assert ctx.clones.record(111111111) is not None

    asyncio.run(scenario())


@pytest.mark.parametrize("user_id", [OWNER, MEMBER])
def test_supervisor_stops_expired_clone_without_deleting_record(tmp_path, user_id):
    async def scenario():
        premium = FakePremium({user_id})
        ctx, _, commands = build(tmp_path, premium=premium)
        await commands["clone"](None, FakeMessage("/clone " + TOKEN_A, uid=user_id))
        premium.ids.clear()
        assert await ctx.clones.supervise() == ()
        assert not ctx.clones.is_running(111111111)
        record = ctx.clones.record(111111111)
        assert record is not None and record.disabled

    asyncio.run(scenario())
