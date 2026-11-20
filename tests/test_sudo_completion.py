"""Delegation is capability-specific; sensitive operations stay Owner-only."""

import asyncio
from contextlib import asynccontextmanager
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.modules import ops
from agent.modules.ops.sudo_commands import build as commands
from agent.platform.sudo_access import SudoAccess, SudoError
from agent.platform.db import Database
from agent.platform.actions import ActionRouter
from test_ops import FakeMessage, ctx as ops_context


def test_readonly_capabilities_are_independent_at_command_boundary(tmp_path):
    async def scenario():
        ctx = ops_context.__wrapped__(tmp_path)
        _, handlers = ops.build(ctx)

        async def allowed(user, capability, scope=0):
            return user == 22 and capability == "health.read" and scope == -100

        with patch.object(SudoAccess, "allowed", side_effect=allowed):
            status = FakeMessage("/watchdog", uid=22)
            status.chat.id = -100
            await handlers["watchdog"](None, status)
            assert "Runtime health" in status.replies[0]
            forbidden = FakeMessage("/watchdog clean", uid=22)
            forbidden.chat.id = -100
            await handlers["watchdog"](None, forbidden)
            assert "reserved" in forbidden.replies[0]
            inventory = FakeMessage("/plugins", uid=22)
            await handlers["plugins"](None, inventory)
            assert "reserved" in inventory.replies[0]
            other = FakeMessage("/watchdog", uid=22)
            other.chat.id = -200
            await handlers["watchdog"](None, other)
            assert "reserved" in other.replies[0]

    asyncio.run(scenario())


def test_plugin_inspection_does_not_grant_mutation_or_callback_rights(tmp_path):
    async def scenario():
        ctx = ops_context.__wrapped__(tmp_path)
        ctx.actions = ActionRouter()
        _, handlers = ops.build(ctx)
        with patch.object(SudoAccess, "allowed", new=AsyncMock(return_value=True)):
            inventory = FakeMessage("/plugins", uid=22)
            await handlers["plugins"](None, inventory)
            assert "Read-only" in inventory.replies[0]
            mutate = FakeMessage("/plugin demo off", uid=22)
            await handlers["plugin"](None, mutate)
            assert "reserved" in mutate.replies[0]
            assert ctx.registry.is_enabled("demo")
            press = SimpleNamespace(
                data="plugin:demo", from_user=SimpleNamespace(id=22), answer=AsyncMock()
            )
            await ctx.actions.dispatch(None, press)
            assert press.answer.await_args.kwargs["show_alert"]
            assert ctx.registry.is_enabled("demo")
            for name in ("restart", "addsudo", "delsudo", "setlog"):
                message = FakeMessage("/" + name, uid=22)
                await handlers[name](None, message)
                assert "reserved" in message.replies[0]

    asyncio.run(scenario())


def test_sudo_history_shows_actor_reason_and_time():
    from datetime import datetime, timezone

    service = SimpleNamespace(
        history=AsyncMock(
            return_value=[
                dict(
                    user_id=22,
                    group_id=-100,
                    capability="diagnostics.read",
                    action="revoke",
                    actor_id=11,
                    reason="<support ended>",
                    created_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
                    expires_at=None,
                    changed=True,
                )
            ]
        )
    )
    message = FakeMessage("/sudolist history")
    message.chat.id = 11
    asyncio.run(
        commands(service, AsyncMock(return_value=True))["sudolist"](None, message)
    )
    assert "&lt;support ended&gt;" in message.replies[0]
    assert "11" in message.replies[0]
    assert "2026-11-15" in message.replies[0]


def test_sudo_permission_catalog_does_not_accidentally_list_all_users():
    service = SimpleNamespace(listing=AsyncMock(return_value=[]))
    message = FakeMessage("/sudoperms")
    message.chat.id = 11
    asyncio.run(
        commands(service, AsyncMock(return_value=True))["sudoperms"](None, message)
    )
    service.listing.assert_not_awaited()
    assert "plugins.inspect" in message.replies[0]
    assert "Owner-only" in message.replies[0]


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="Database required"
)
def test_pg_sudo_concurrent_audits_expiry_metadata_and_rollback():
    async def scenario():
        scope = "sudo-batch:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=scope, required=True)
            for _ in range(2)
        ]
        try:
            for db in dbs:
                assert await db.connect()
            services = [SudoAccess(db, owner_id=11) for db in dbs]
            await asyncio.gather(
                *(
                    services[i % 2].grant(
                        11,
                        22,
                        "plugins.inspect",
                        group_id=-100,
                        hours=1,
                        reason=f"grant {i}",
                    )
                    for i in range(12)
                )
            )
            assert len(await services[0].listing(11)) == 1
            assert len(await services[1].history(11)) == 12
            assert await services[1].allowed(22, "plugins.inspect", -100)
            assert not await services[1].allowed(22, "diagnostics.read", -100)
            await services[0].revoke(
                11, 22, "plugins.inspect", group_id=-100, reason="ended"
            )
            assert (await services[1].history(11))[0]["expires_at"] is not None
            assert not await services[1].allowed(22, "plugins.inspect", -100)
            for capability in (
                "sudo.manage",
                "premium.manage",
                "plugins.approve",
                "clones.start",
                "system.restart",
            ):
                with pytest.raises(SudoError):
                    await services[0].grant(
                        11, 22, capability, hours=1, reason="sensitive"
                    )
            await services[0].grant(11, 44, "health.read", reason="existing grant")
            original = dbs[0]._pool

            class FailAudit:
                def __init__(self, conn):
                    self.conn = conn

                def __getattr__(self, key):
                    return getattr(self.conn, key)

                async def execute(self, sql, *args, **kwargs):
                    if "INSERT INTO agent_sudo_audit" in sql:
                        raise RuntimeError("injected audit outage")
                    return await self.conn.execute(sql, *args, **kwargs)

            class Pool:
                @asynccontextmanager
                async def acquire(self, **kwargs):
                    async with original.acquire(**kwargs) as conn:
                        yield FailAudit(conn)

            dbs[0]._pool = Pool()
            try:
                with pytest.raises(SudoError, match="not confirmed"):
                    await services[0].grant(
                        11, 33, "health.read", reason="rollback check"
                    )
                with pytest.raises(SudoError, match="not confirmed"):
                    await services[0].revoke(
                        11, 44, "health.read", reason="revoke rollback check"
                    )
            finally:
                dbs[0]._pool = original
            assert not await services[1].allowed(33, "health.read")
            assert await services[1].allowed(44, "health.read")
            assert len(await services[1].history(11)) == 14
            assert len(await services[1].history(11, page=1, page_size=5)) == 5
        finally:
            if dbs[0].connected:
                async with dbs[0]._pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM agent_sudo_grants WHERE tenant=$1", scope
                    )
                    await conn.execute(
                        "DELETE FROM agent_sudo_audit WHERE tenant=$1", scope
                    )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())


def test_sudo_pages_fit_classic_telegram_utf16_limit():
    from datetime import datetime, timezone
    from agent.modules.ops.sudo_commands import PAGE_SIZE
    from agent.utils.sender import _visible_text

    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    service = SimpleNamespace(
        listing=AsyncMock(
            return_value=[
                dict(
                    user_id=9223372036854775806,
                    capability="diagnostics.read",
                    group_id=-1001234567890,
                    expires_at=now,
                    granted_at=now,
                    granted_by=9223372036854775805,
                    reason="😁" * 300,
                    active=True,
                )
                for _ in range(PAGE_SIZE)
            ]
        )
    )
    message = FakeMessage("/sudolist")
    message.chat.id = 11
    asyncio.run(
        commands(service, AsyncMock(return_value=True))["sudolist"](None, message)
    )
    assert len(_visible_text(message.replies[0]).encode("utf-16-le")) // 2 < 4096


@pytest.mark.parametrize("text", ["/sudolist 1 extra", "/sudoperms 22 1 extra"])
def test_surplus_sudo_page_arguments_are_rejected(text):
    service = SimpleNamespace(listing=AsyncMock(return_value=[]))
    message = FakeMessage(text)
    message.chat.id = 11
    asyncio.run(
        commands(service, AsyncMock(return_value=True))[text.split()[0][1:]](
            None, message
        )
    )
    service.listing.assert_not_awaited()
    assert "at most one" in message.replies[0]


def test_owner_only_denylist_survives_catalog_misconfiguration(monkeypatch):
    import agent.platform.sudo_access as module

    async def scenario():
        monkeypatch.setattr(
            module, "CAPABILITIES", module.CAPABILITIES | {"system.restart"}
        )
        service = SudoAccess(SimpleNamespace(connected=False), owner_id=11)
        with pytest.raises(SudoError, match="Owner-only"):
            await service.grant(11, 22, "system.restart", reason="must not delegate")
        assert not await service.allowed(22, "system.restart")

    asyncio.run(scenario())
