"""Capabilities are scoped, expiring and never Owner/Premium substitutes."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.platform.sudo_access import SudoAccess, SudoError
from agent.platform.db import Database


def test_sudo_outage_and_sensitive_capabilities_fail_closed():
    async def scenario():
        service = SudoAccess(SimpleNamespace(connected=False), owner_id=1)
        assert not await service.allowed(2, "diagnostics.read", -100)
        with pytest.raises(SudoError):
            await service.grant(2, 3, "diagnostics.read", reason="self grant")
        with pytest.raises(SudoError):
            await service.grant(1, 3, "plugins.approve", reason="sensitive")

    asyncio.run(scenario())


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="Database required"
)
def test_pg_sudo_scopes_revocation_audit_and_tenant_isolation():
    async def scenario():
        scope = "sudo-test:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":clone")
        ]
        try:
            for db in dbs:
                assert await db.connect()
            services = [SudoAccess(db, owner_id=1) for db in dbs]
            await services[0].grant(
                1, 2, "diagnostics.read", group_id=-100, hours=1, reason="group support"
            )
            assert await services[1].allowed(2, "diagnostics.read", -100)
            assert not await services[1].allowed(2, "diagnostics.read", -200)
            assert not await services[1].allowed(2, "diagnostics.read")
            assert not await services[2].allowed(2, "diagnostics.read", -100)
            assert not await services[1].allowed(2, "plugins.approve", -100)
            with pytest.raises(SudoError):
                await services[1].revoke(
                    2, 2, "diagnostics.read", group_id=-100, reason="self revoke"
                )
            assert await services[1].revoke(
                1, 2, "diagnostics.read", group_id=-100, reason="support ended"
            )
            assert not await services[0].allowed(2, "diagnostics.read", -100)
            await services[0].grant(
                1, 2, "diagnostics.read", hours=1, reason="global support"
            )
            assert await services[1].allowed(2, "diagnostics.read", -200)
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE agent_sudo_grants SET expires_at=now()-interval '1 second' WHERE tenant=$1",
                    scope,
                )
            assert not await services[1].allowed(2, "diagnostics.read", -100)
            rows = await services[0].listing(1)
            assert len(rows) == 1  # expiration preserves the record
            history = await services[1].history(1)
            assert [r["action"] for r in history] == ["grant", "revoke", "grant"]
            assert history[1]["reason"] == "support ended"
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_sudo_grants WHERE tenant=$1", db.scope
                        )
                        await conn.execute(
                            "DELETE FROM agent_sudo_audit WHERE tenant=$1", db.scope
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())
