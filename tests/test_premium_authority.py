"""Canonical entitlements must survive stale clients and fail closed on outages."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from agent.platform.db import Database
from agent.platform.premium import PremiumBook


def test_entitlement_outage_denies_cached_premium(tmp_path):
    async def scenario():
        book = PremiumBook(tmp_path, db=SimpleNamespace(connected=False))
        book._data["users"]["7"] = {"until": None}
        assert not await book.ais_premium(7)

    asyncio.run(scenario())


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_DATABASE_URL"), reason="Database required"
)
def test_authoritative_grants_revocations_isolation_and_legacy_import(tmp_path):
    async def scenario():
        scope = "premium-test:" + uuid.uuid4().hex
        dbs = [
            Database(os.environ["AGENT_TEST_DATABASE_URL"], scope=s, required=True)
            for s in (scope, scope, scope + ":other")
        ]
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            async with dbs[0]._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)",
                    dbs[0].name_for("premium"),
                    '{"users":{"7":{"until":null}},"usage":{}}',
                )
            books = [PremiumBook(tmp_path / str(i), db=db) for i, db in enumerate(dbs)]
            assert await books[0].ais_premium(7)
            assert not await books[2].ais_premium(7)
            assert await books[1].arevoke(7)
            # Legacy writes cannot resurrect an imported/revoked entitlement.
            assert not await books[0].ais_premium(7)
            await asyncio.gather(*(books[i % 2].agrant(8, 1, by=1) for i in range(10)))
            assert await books[1].ais_premium(8)
            async with dbs[0]._pool.acquire() as conn:
                remaining = await conn.fetchval(
                    "SELECT until_epoch-extract(epoch from now()) FROM agent_premium_entitlements WHERE tenant=$1 AND user_id=8",
                    scope,
                )
            assert 9.99 * 86400 < remaining <= 10 * 86400
            assert await books[0].arevoke(8)
            assert not await books[1].ais_premium(8)
        finally:
            for db in (dbs[0], dbs[2]):
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM agent_premium_tenants WHERE tenant=$1",
                            db.scope,
                        )
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name=$1",
                            db.name_for("premium"),
                        )
            for db in dbs:
                await db.close()

    asyncio.run(scenario())
