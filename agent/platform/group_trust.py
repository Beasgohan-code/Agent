"""Canonical trusted-member exemptions with serialized toggles and atomic audit."""

import json

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_group_trust (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    members BIGINT[] NOT NULL DEFAULT '{}', version BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_group_trust_revisions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
    target_id BIGINT NOT NULL, actor_id BIGINT NOT NULL, trusted BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,version),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_group_trust(tenant,group_id))""",
)


class TrustError(RuntimeError):
    """Trusted-member state is not confirmed."""


async def trusted_members(ctx, group_id, *, toggle=None, actor=None, approved=None):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise TrustError("Approvals belong to a group.")
    if toggle is not None and (
        type(toggle) is not int
        or not 0 < toggle < 2**63
        or type(actor) is not int
        or not 0 < actor < 2**63
    ):
        raise TrustError("Personal member and administrator identities are required.")
    if approved is not None and (type(approved) is not bool or toggle is None):
        raise TrustError("Invalid approval state.")
    db = getattr(ctx, "db", None)
    if db is None:
        if toggle is not None and (
            approved is None or ctx.chats.is_trusted(group_id, toggle) != approved
        ):
            result = ctx.chats.toggle_trust(group_id, toggle)
            ctx.chats.log(
                group_id,
                "approve" if result else "unapprove",
                actor_id=actor,
                target_id=toggle,
            )
        return {
            int(uid)
            for uid, member in ctx.chats._chat(group_id)["members"].items()
            if member.get("trusted")
        }
    if not db.connected or getattr(db, "_pool", None) is None:
        raise TrustError("Database approval state unavailable. No changes confirmed.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for(f"trust:{group_id}"),
                    timeout=5,
                )
                row = await conn.fetchrow(
                    "SELECT members,version FROM agent_group_trust WHERE tenant=$1 AND group_id=$2",
                    db.scope,
                    group_id,
                    timeout=5,
                )
                if row is None:
                    raw = await conn.fetchval(
                        "SELECT value FROM agent_documents WHERE name=$1",
                        db.name_for("chats"),
                        timeout=5,
                    )
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    legacy = (raw or {}).get(str(group_id), {}).get("members", {})
                    members = {
                        int(uid)
                        for uid, member in legacy.items()
                        if member.get("trusted")
                    }
                    if any(not 0 < uid < 2**63 for uid in members):
                        raise TrustError("Persisted legacy trust state invalid.")
                    await conn.execute(
                        "INSERT INTO agent_group_trust(tenant,group_id,members) VALUES($1,$2,$3)",
                        db.scope,
                        group_id,
                        sorted(members),
                        timeout=5,
                    )
                    row = {"members": members, "version": 0}
                members = set(row["members"])
                if toggle is not None:
                    enabled = toggle not in members if approved is None else approved
                    if (toggle in members) == enabled:
                        return members
                    members.symmetric_difference_update({toggle})
                    version = row["version"] + 1
                    await conn.execute(
                        "UPDATE agent_group_trust SET members=$3,version=$4 WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        sorted(members),
                        version,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_group_trust_revisions(tenant,group_id,version,target_id,actor_id,trusted) VALUES($1,$2,$3,$4,$5,$6)",
                        db.scope,
                        group_id,
                        version,
                        toggle,
                        actor,
                        enabled,
                        timeout=5,
                    )
        return members
    except TrustError:
        raise
    except Exception:
        raise TrustError(
            "Approval state unavailable or result unconfirmed. Refresh before retrying."
        ) from None


async def trust_history(ctx, group_id):
    db = getattr(ctx, "db", None)
    if db is None:
        return []
    if not db.connected or getattr(db, "_pool", None) is None:
        raise TrustError("Approval history unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(
                """SELECT actor_id,target_id,trusted,extract(epoch from created_at) AS at
                FROM agent_group_trust_revisions WHERE tenant=$1 AND group_id=$2 ORDER BY version DESC LIMIT 10""",
                db.scope,
                group_id,
                timeout=5,
            )
        return [
            {
                "action": "approve" if row["trusted"] else "unapprove",
                "actor": row["actor_id"],
                "target": row["target_id"],
                "at": float(row["at"]),
                "reason": "",
            }
            for row in rows
        ]
    except Exception:
        raise TrustError("Approval history unavailable.") from None
