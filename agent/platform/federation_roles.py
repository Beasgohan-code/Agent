"""Expiring federation role consent, serialized with federation metadata changes."""

import uuid
from .federations import FederationError, fed_id

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_federation_invitations (
    tenant TEXT NOT NULL, id UUID NOT NULL, fed_id UUID NOT NULL,
    invited_by BIGINT NOT NULL CHECK(invited_by>0), target_id BIGINT NOT NULL CHECK(target_id>0),
    kind TEXT NOT NULL CHECK(kind IN ('admin','owner')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '10 minutes',
    PRIMARY KEY(tenant,id), UNIQUE(tenant,fed_id,target_id,kind),
    FOREIGN KEY(tenant,fed_id) REFERENCES agent_federations(tenant,id) ON DELETE CASCADE)""",
    """ALTER TABLE agent_federation_history ADD COLUMN IF NOT EXISTS target_id BIGINT""",
)


async def change(
    ctx, action, actor, *, federation=None, target=None, invitation=None, kind="admin"
):
    if type(actor) is not int or not 0 < actor < 2**63:
        raise FederationError("Use your personal Telegram identity.")
    if action not in (
        "invite",
        "accept",
        "decline",
        "demote",
        "resign",
    ) or kind not in ("admin", "owner"):
        raise FederationError("Invalid federation role operation.")
    if action in ("invite", "demote") and (
        type(target) is not int or not 0 < target < 2**63
    ):
        raise FederationError("Provide a valid personal user ID.")
    identity = fed_id(federation) if federation is not None else None
    token = fed_id(invitation) if invitation is not None else None
    db = getattr(ctx, "db", None)
    if db is None or not db.connected or getattr(db, "_pool", None) is None:
        raise FederationError(
            "PostgreSQL federation roles unavailable. No changes confirmed."
        )
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for("federations"),
                    timeout=5,
                )
                if action in ("accept", "decline"):
                    invite = await conn.fetchrow(
                        "SELECT * FROM agent_federation_invitations WHERE tenant=$1 AND id=$2 AND expires_at>now()",
                        db.scope,
                        token,
                        timeout=5,
                    )
                    if invite is None or invite["target_id"] != actor:
                        raise FederationError(
                            "This invitation is expired, revoked, already used, or belongs to another user."
                        )
                    identity, target, kind = invite["fed_id"], actor, invite["kind"]
                if identity is None:
                    identity = await conn.fetchval(
                        "SELECT id FROM agent_federations WHERE tenant=$1 AND owner_id=$2",
                        db.scope,
                        actor,
                        timeout=5,
                    )
                row = await conn.fetchrow(
                    "SELECT * FROM agent_federations WHERE tenant=$1 AND id=$2",
                    db.scope,
                    identity,
                    timeout=5,
                )
                if row is None:
                    raise FederationError("Federation not found.")
                if action in ("invite", "demote") and row["owner_id"] != actor:
                    raise FederationError(
                        "Only the current federation owner can manage these roles."
                    )
                if (
                    action in ("accept", "decline")
                    and invite["invited_by"] != row["owner_id"]
                ):
                    raise FederationError(
                        "Federation ownership changed; request a new invitation."
                    )
                audit_action = action
                if action == "invite":
                    if target == row["owner_id"]:
                        raise FederationError(
                            "The federation owner already has full authority."
                        )
                    if kind == "owner" and await conn.fetchval(
                        "SELECT 1 FROM agent_federations WHERE tenant=$1 AND owner_id=$2",
                        db.scope,
                        target,
                        timeout=5,
                    ):
                        raise FederationError(
                            "The recipient already owns a federation."
                        )
                    if kind == "admin" and await conn.fetchval(
                        "SELECT 1 FROM agent_federation_admins WHERE tenant=$1 AND fed_id=$2 AND user_id=$3",
                        db.scope,
                        identity,
                        target,
                        timeout=5,
                    ):
                        raise FederationError(
                            "This user is already a federation administrator."
                        )
                    # Remove expired invitations and supersede the target's old token.
                    await conn.execute(
                        "DELETE FROM agent_federation_invitations WHERE tenant=$1 AND expires_at<=now()",
                        db.scope,
                        timeout=5,
                    )
                    token = uuid.uuid4()
                    await conn.execute(
                        """INSERT INTO agent_federation_invitations(tenant,id,fed_id,invited_by,target_id,kind) VALUES($1,$2,$3,$4,$5,$6)
                        ON CONFLICT(tenant,fed_id,target_id,kind) DO UPDATE SET id=EXCLUDED.id,invited_by=EXCLUDED.invited_by,expires_at=now()+interval '10 minutes' """,
                        db.scope,
                        token,
                        identity,
                        actor,
                        target,
                        kind,
                        timeout=5,
                    )
                    audit_action = "invite:" + kind
                elif action == "accept":
                    if kind == "owner":
                        if await conn.fetchval(
                            "SELECT 1 FROM agent_federations WHERE tenant=$1 AND owner_id=$2",
                            db.scope,
                            actor,
                            timeout=5,
                        ):
                            raise FederationError(
                                "You already own a federation; transfer was not applied."
                            )
                        await conn.execute(
                            "UPDATE agent_federations SET owner_id=$3 WHERE tenant=$1 AND id=$2",
                            db.scope,
                            identity,
                            actor,
                            timeout=5,
                        )
                        await conn.execute(
                            "DELETE FROM agent_federation_admins WHERE tenant=$1 AND fed_id=$2 AND user_id IN ($3,$4)",
                            db.scope,
                            identity,
                            actor,
                            row["owner_id"],
                            timeout=5,
                        )
                        await conn.execute(
                            "DELETE FROM agent_federation_invitations WHERE tenant=$1 AND fed_id=$2",
                            db.scope,
                            identity,
                            timeout=5,
                        )
                    else:
                        await conn.execute(
                            "INSERT INTO agent_federation_admins(tenant,fed_id,user_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                            db.scope,
                            identity,
                            actor,
                            timeout=5,
                        )
                        await conn.execute(
                            "DELETE FROM agent_federation_invitations WHERE tenant=$1 AND id=$2",
                            db.scope,
                            token,
                            timeout=5,
                        )
                    audit_action = "accept:" + kind
                elif action == "decline":
                    await conn.execute(
                        "DELETE FROM agent_federation_invitations WHERE tenant=$1 AND id=$2",
                        db.scope,
                        token,
                        timeout=5,
                    )
                    audit_action = "decline:" + kind
                else:
                    if action == "resign":
                        target = actor
                    if target == row["owner_id"]:
                        raise FederationError(
                            "The federation owner cannot be demoted. Transfer or delete the federation instead."
                        )
                    if action == "resign" and not await conn.fetchval(
                        "SELECT 1 FROM agent_federation_admins WHERE tenant=$1 AND fed_id=$2 AND user_id=$3",
                        db.scope,
                        identity,
                        actor,
                        timeout=5,
                    ):
                        raise FederationError(
                            "You are not an administrator in this federation."
                        )
                    await conn.execute(
                        "DELETE FROM agent_federation_admins WHERE tenant=$1 AND fed_id=$2 AND user_id=$3",
                        db.scope,
                        identity,
                        target,
                        timeout=5,
                    )
                    await conn.execute(
                        "DELETE FROM agent_federation_invitations WHERE tenant=$1 AND fed_id=$2 AND target_id=$3",
                        db.scope,
                        identity,
                        target,
                        timeout=5,
                    )
                await conn.execute(
                    "INSERT INTO agent_federation_history(tenant,fed_id,actor_id,action,target_id) VALUES($1,$2,$3,$4,$5)",
                    db.scope,
                    identity,
                    actor,
                    audit_action,
                    target,
                    timeout=5,
                )
                return {
                    "id": identity,
                    "name": row["name"],
                    "invitation": token,
                    "kind": kind,
                    "target": target,
                }
    except FederationError:
        raise
    except Exception:
        raise FederationError(
            "Federation role result unconfirmed. Refresh before retrying."
        ) from None
