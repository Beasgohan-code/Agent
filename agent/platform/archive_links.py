"""Tenant-scoped archive range tokens; no local-file fallback."""

import secrets
import re

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_archive_links (
    tenant TEXT NOT NULL, token TEXT NOT NULL, owner_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL CHECK(channel_id<0), first_id BIGINT NOT NULL CHECK(first_id>0),
    last_id BIGINT NOT NULL CHECK(last_id>=first_id AND last_id-first_id<50),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '24 hours', PRIMARY KEY(tenant,token))""",
    "ALTER TABLE agent_archive_links ADD COLUMN IF NOT EXISTS revoked BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE agent_archive_links ADD COLUMN IF NOT EXISTS message_ids BIGINT[]",
    "ALTER TABLE agent_archive_links ADD COLUMN IF NOT EXISTS max_uses INTEGER",
    "ALTER TABLE agent_archive_links ADD COLUMN IF NOT EXISTS uses INTEGER NOT NULL DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS agent_archive_deliveries (
    tenant TEXT NOT NULL, token TEXT NOT NULL, user_id BIGINT NOT NULL, message_id BIGINT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending', delivered INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(tenant,token,user_id,message_id), FOREIGN KEY(tenant,token)
    REFERENCES agent_archive_links(tenant,token))""",
    """CREATE TABLE IF NOT EXISTS agent_archive_delivery_items (
    tenant TEXT NOT NULL, token TEXT NOT NULL, user_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL, source_id BIGINT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending', destination_id BIGINT,
    PRIMARY KEY(tenant,token,user_id,message_id,source_id),
    FOREIGN KEY(tenant,token,user_id,message_id)
    REFERENCES agent_archive_deliveries(tenant,token,user_id,message_id) ON DELETE CASCADE)""",
)


def database(ctx):
    db = getattr(ctx, "db", None)
    if db is None or not db.connected or getattr(db, "_pool", None) is None:
        raise ValueError(
            "PostgreSQL archive links unavailable. No link or delivery confirmed."
        )
    return db


async def create(
    ctx, actor, channel, first, last, *, message_ids=None, hours=24, max_uses=None
):
    if (
        type(hours) is not int
        or not 1 <= hours <= 168
        or (
            max_uses is not None
            and (type(max_uses) is not int or not 1 <= max_uses <= 10000)
        )
    ):
        raise ValueError("Expiry must be 1–168 hours; use limit must be 1–10000.")
    if message_ids is not None:
        if (
            not isinstance(message_ids, list)
            or not 1 <= len(message_ids) <= 50
            or any(type(mid) is not int or not 0 < mid < 2**31 for mid in message_ids)
            or len(set(message_ids)) != len(message_ids)
        ):
            raise ValueError("Choose 1–50 unique valid archive message IDs.")
        first = last = message_ids[0]
    if (
        type(actor) is not int
        or not 0 < actor < 2**63
        or type(channel) is not int
        or not -(2**63) < channel < 0
        or any(type(v) is not int or not 0 < v < 2**31 for v in (first, last))
        or not 0 <= last - first < 50
    ):
        raise ValueError("Choose an ascending archive message range of 1–50 messages.")
    db = database(ctx)
    token = secrets.token_urlsafe(24)
    async with db._pool.acquire(timeout=5) as conn:
        await conn.execute(
            "INSERT INTO agent_archive_links(tenant,token,owner_id,channel_id,first_id,last_id,message_ids,expires_at,max_uses) VALUES($1,$2,$3,$4,$5,$6,$7,now()+$8*interval '1 hour',$9)",
            db.scope,
            token,
            actor,
            channel,
            first,
            last,
            message_ids,
            hours,
            max_uses,
            timeout=5,
        )
    return token


async def revoke(ctx, actor, token):
    if (
        type(actor) is not int
        or not 0 < actor < 2**63
        or not isinstance(token, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32}", token)
    ):
        raise ValueError("Provide an archive token created by you in this bot.")
    db = database(ctx)
    async with db._pool.acquire(timeout=5) as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT owner_id,revoked FROM agent_archive_links WHERE tenant=$1 AND token=$2 FOR UPDATE",
                db.scope,
                token,
                timeout=5,
            )
            if row is None or row["owner_id"] != actor:
                raise ValueError(
                    "Archive link not found or not owned by you in this bot."
                )
            if row["revoked"]:
                return False
            await conn.execute(
                "UPDATE agent_archive_links SET revoked=true WHERE tenant=$1 AND token=$2",
                db.scope,
                token,
                timeout=5,
            )
    return True
