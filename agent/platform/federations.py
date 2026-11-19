"""Tenant-scoped federation ownership and membership with transactional audit.

Federation metadata is not ban enforcement. Cross-chat delivery must be added
before ban commands are advertised. No local fallback or deployment-wide grants.
"""

import uuid

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_federations (
    tenant TEXT NOT NULL, id UUID NOT NULL, owner_id BIGINT NOT NULL CHECK(owner_id>0),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    require_reason BOOLEAN NOT NULL DEFAULT false, notify_owner BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,id), UNIQUE(tenant,owner_id))""",
    """CREATE TABLE IF NOT EXISTS agent_federation_admins (
    tenant TEXT NOT NULL, fed_id UUID NOT NULL, user_id BIGINT NOT NULL CHECK(user_id>0),
    PRIMARY KEY(tenant,fed_id,user_id), FOREIGN KEY(tenant,fed_id)
    REFERENCES agent_federations(tenant,id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS agent_federation_chats (
    tenant TEXT NOT NULL, chat_id BIGINT NOT NULL CHECK(chat_id<0), fed_id UUID NOT NULL,
    joined_by BIGINT NOT NULL, quiet BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY(tenant,chat_id), FOREIGN KEY(tenant,fed_id)
    REFERENCES agent_federations(tenant,id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS agent_federation_history (
    id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, fed_id UUID NOT NULL,
    actor_id BIGINT NOT NULL, action TEXT NOT NULL, chat_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), FOREIGN KEY(tenant,fed_id)
    REFERENCES agent_federations(tenant,id) ON DELETE CASCADE)""",
)


class FederationError(RuntimeError):
    """Federation operation denied or not confirmed."""


def fed_id(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise FederationError("Provide a valid federation ID.") from None


async def operate(
    ctx,
    action,
    actor,
    *,
    federation=None,
    chat=None,
    name=None,
    enabled=None,
    client=None,
):
    if type(actor) is not int or not 0 < actor < 2**63:
        raise FederationError("Use your personal Telegram identity.")
    if chat is not None and (type(chat) is not int or not -(2**63) < chat < 0):
        raise FederationError("Use this command inside a group.")
    if action not in (
        "new",
        "rename",
        "delete",
        "info",
        "admins",
        "mine",
        "join",
        "leave",
        "chat",
        "reason",
        "notify",
        "quiet",
    ):
        raise FederationError("Unknown federation operation.")
    if action in ("new", "rename") and (
        not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
    ):
        raise FederationError("Federation names must contain 1–100 characters.")
    if action in ("reason", "notify", "quiet") and type(enabled) is not bool:
        raise FederationError("Choose yes, no, on or off.")
    if action in ("join", "leave", "chat", "quiet") and chat is None:
        raise FederationError("Use this command inside a group.")
    identity = fed_id(federation) if federation is not None else None
    db = getattr(ctx, "db", None)
    if db is None or not db.connected or getattr(db, "_pool", None) is None:
        raise FederationError(
            "Database federations unavailable. No changes confirmed."
        )
    if action in ("join", "leave", "quiet"):
        from pyrogram.enums import ChatMemberStatus

        try:
            member = await client.get_chat_member(chat, actor)
        except Exception:
            raise FederationError("Chat ownership could not be verified.") from None
        if getattr(member, "status", None) != ChatMemberStatus.OWNER:
            raise FederationError(
                "Only the current Telegram chat owner can change federation membership or chat preferences."
            )
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                # A tenant-wide lock also serializes one-owner and one-chat constraints.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for("federations"),
                    timeout=5,
                )
                if action == "new":
                    identity = uuid.uuid4()
                    if await conn.fetchval(
                        "SELECT 1 FROM agent_federations WHERE tenant=$1 AND owner_id=$2",
                        db.scope,
                        actor,
                        timeout=5,
                    ):
                        raise FederationError(
                            "You already own a federation. Use /myfeds."
                        )
                    row = await conn.fetchrow(
                        "INSERT INTO agent_federations(tenant,id,owner_id,name) VALUES($1,$2,$3,$4) RETURNING *",
                        db.scope,
                        identity,
                        actor,
                        name.strip(),
                        timeout=5,
                    )
                elif action == "mine":
                    return [
                        dict(row)
                        for row in await conn.fetch(
                            """SELECT f.* FROM agent_federations f WHERE f.tenant=$1 AND
                        (f.owner_id=$2 OR EXISTS(SELECT 1 FROM agent_federation_admins a WHERE a.tenant=f.tenant AND a.fed_id=f.id AND a.user_id=$2))
                        ORDER BY f.created_at,f.id LIMIT 101""",
                            db.scope,
                            actor,
                            timeout=5,
                        )
                    ]
                else:
                    if action in ("chat", "leave", "quiet"):
                        identity = await conn.fetchval(
                            "SELECT fed_id FROM agent_federation_chats WHERE tenant=$1 AND chat_id=$2",
                            db.scope,
                            chat,
                            timeout=5,
                        )
                        if identity is None:
                            raise FederationError("This chat is not in a federation.")
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
                        raise FederationError(
                            "Federation not found. Provide its ID, or create one with /newfed."
                        )
                    if (
                        action in ("rename", "delete", "reason", "notify")
                        and row["owner_id"] != actor
                    ):
                        raise FederationError("Only the federation owner can do this.")
                    if action == "admins":
                        admins = await conn.fetch(
                            "SELECT user_id FROM agent_federation_admins WHERE tenant=$1 AND fed_id=$2 ORDER BY user_id LIMIT 101",
                            db.scope,
                            identity,
                            timeout=5,
                        )
                        return {
                            "owner": row["owner_id"],
                            "admins": [r["user_id"] for r in admins],
                        }
                    if action == "info":
                        result = dict(row)
                        result["chats"] = await conn.fetchval(
                            "SELECT count(*) FROM agent_federation_chats WHERE tenant=$1 AND fed_id=$2",
                            db.scope,
                            identity,
                            timeout=5,
                        )
                        return result
                    if action == "chat":
                        result = dict(row)
                        result["quiet"] = await conn.fetchval(
                            "SELECT quiet FROM agent_federation_chats WHERE tenant=$1 AND chat_id=$2",
                            db.scope,
                            chat,
                            timeout=5,
                        )
                        return result
                    if action == "join":
                        if await conn.fetchval(
                            "SELECT 1 FROM agent_federation_chats WHERE tenant=$1 AND chat_id=$2",
                            db.scope,
                            chat,
                            timeout=5,
                        ):
                            raise FederationError(
                                "This chat already belongs to a federation. Leave it first."
                            )
                        await conn.execute(
                            "INSERT INTO agent_federation_chats(tenant,chat_id,fed_id,joined_by) VALUES($1,$2,$3,$4)",
                            db.scope,
                            chat,
                            identity,
                            actor,
                            timeout=5,
                        )
                    elif action == "leave":
                        await conn.execute(
                            "DELETE FROM agent_federation_chats WHERE tenant=$1 AND chat_id=$2",
                            db.scope,
                            chat,
                            timeout=5,
                        )
                    elif action == "delete":
                        await conn.execute(
                            "DELETE FROM agent_federations WHERE tenant=$1 AND id=$2",
                            db.scope,
                            identity,
                            timeout=5,
                        )
                        return dict(
                            row
                        )  # CASCADE removes metadata, never calls Telegram unban.
                    elif action == "rename":
                        row = await conn.fetchrow(
                            "UPDATE agent_federations SET name=$3 WHERE tenant=$1 AND id=$2 RETURNING *",
                            db.scope,
                            identity,
                            name.strip(),
                            timeout=5,
                        )
                    elif action in ("reason", "notify"):
                        column = (
                            "require_reason" if action == "reason" else "notify_owner"
                        )
                        row = await conn.fetchrow(
                            f"UPDATE agent_federations SET {column}=$3 WHERE tenant=$1 AND id=$2 RETURNING *",
                            db.scope,
                            identity,
                            enabled,
                            timeout=5,
                        )
                    elif action == "quiet":
                        await conn.execute(
                            "UPDATE agent_federation_chats SET quiet=$3 WHERE tenant=$1 AND chat_id=$2",
                            db.scope,
                            chat,
                            enabled,
                            timeout=5,
                        )
                await conn.execute(
                    "INSERT INTO agent_federation_history(tenant,fed_id,actor_id,action,chat_id) VALUES($1,$2,$3,$4,$5)",
                    db.scope,
                    identity,
                    actor,
                    action,
                    chat,
                    timeout=5,
                )
                return dict(row)
    except FederationError:
        raise
    except Exception:
        raise FederationError(
            "Federation result unconfirmed. Refresh before retrying."
        ) from None
