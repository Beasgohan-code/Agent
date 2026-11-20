"""Relational Premium authority, seeded once from each tenant's legacy ledger.

Schema statements are additive, idempotent startup migrations. Legacy usage
writers cannot overwrite this authority after its first import. During rollout,
quiesce old instances: old grant commands do not write these tables.
"""

import json
import time

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_premium_tenants (
        tenant TEXT PRIMARY KEY, imported_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS agent_premium_entitlements (
        tenant TEXT NOT NULL REFERENCES agent_premium_tenants(tenant) ON DELETE CASCADE,
        user_id BIGINT NOT NULL CHECK(user_id > 0), until_epoch DOUBLE PRECISION,
        granted_by BIGINT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(tenant,user_id))""",
)


class EntitlementError(RuntimeError):
    """The authoritative entitlement operation was not confirmed."""


async def operate(db, operation, user_id, *, days=30, by=None):
    if type(user_id) is not int or not 0 < user_id < 2**63:
        raise EntitlementError("A positive Telegram user id is required.")
    if not db.connected or getattr(db, "_pool", None) is None:
        raise EntitlementError("Database entitlement state is unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for("premium-authority"),
                    timeout=5,
                )
                imported = await conn.fetchval(
                    "SELECT 1 FROM agent_premium_tenants WHERE tenant=$1",
                    db.scope,
                    timeout=5,
                )
                if not imported:
                    # Lock the legacy row while taking its one-time snapshot.
                    raw = await conn.fetchval(
                        "SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE",
                        db.name_for("premium"),
                        timeout=5,
                    )
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    users = (raw or {}).get("users", {})
                    if not isinstance(users, dict):
                        raise EntitlementError("Legacy entitlement state is invalid.")
                    await conn.execute(
                        "INSERT INTO agent_premium_tenants(tenant) VALUES($1)",
                        db.scope,
                        timeout=5,
                    )
                    for uid, entry in users.items():
                        await conn.execute(
                            "INSERT INTO agent_premium_entitlements(tenant,user_id,until_epoch,granted_by) VALUES($1,$2,$3,$4)",
                            db.scope,
                            int(uid),
                            entry.get("until"),
                            entry.get("by"),
                            timeout=5,
                        )
                if operation == "list":
                    rows = await conn.fetch(
                        "SELECT user_id,until_epoch,granted_by FROM agent_premium_entitlements WHERE tenant=$1 ORDER BY updated_at DESC,user_id LIMIT 50",
                        db.scope,
                        timeout=5,
                    )
                    return [
                        {
                            "user_id": r["user_id"],
                            "until": r["until_epoch"],
                            "by": r["granted_by"],
                        }
                        for r in rows
                    ]
                now = time.time()
                row = await conn.fetchrow(
                    "SELECT until_epoch FROM agent_premium_entitlements WHERE tenant=$1 AND user_id=$2",
                    db.scope,
                    user_id,
                    timeout=5,
                )
                if operation == "record":
                    return None if row is None else {"until": row["until_epoch"]}
                if operation == "check":
                    return row is not None and (
                        row["until_epoch"] is None or row["until_epoch"] > now
                    )
                if operation == "revoke":
                    await conn.execute(
                        "DELETE FROM agent_premium_entitlements WHERE tenant=$1 AND user_id=$2",
                        db.scope,
                        user_id,
                        timeout=5,
                    )
                    return row is not None
                if operation != "grant":
                    raise EntitlementError("Unknown entitlement operation.")
                until = (
                    None
                    if days <= 0
                    else max(now, (row["until_epoch"] or now) if row else now)
                    + days * 86400
                )
                await conn.execute(
                    """INSERT INTO agent_premium_entitlements(tenant,user_id,until_epoch,granted_by)
                    VALUES($1,$2,$3,$4) ON CONFLICT(tenant,user_id) DO UPDATE
                    SET until_epoch=EXCLUDED.until_epoch,granted_by=EXCLUDED.granted_by,updated_at=now()""",
                    db.scope,
                    user_id,
                    until,
                    by,
                    timeout=5,
                )
                return until
    except EntitlementError:
        raise
    except Exception:
        raise EntitlementError(
            "Entitlement result was not confirmed; check before retrying."
        ) from None
