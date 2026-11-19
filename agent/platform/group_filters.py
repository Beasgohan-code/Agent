"""Awaited, serialized group filter snapshots; text JSON preserves match order."""

import json

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_group_filters (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    payload TEXT NOT NULL, version BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_group_filter_revisions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
    payload TEXT NOT NULL, actor_id BIGINT NOT NULL, operation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,version),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_group_filters(tenant,group_id))""",
)


class FilterError(RuntimeError):
    """Authoritative filter operation could not be confirmed."""


async def operate(ctx, group_id, *, name=None, body=None, actor=None):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise FilterError("Filters belong to a group.")
    if name is not None:
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise FilterError("Filter names must contain 1–64 characters.")
        name = name.strip().lower()
        if type(actor) is not int or not 0 < actor < 2**63:
            raise FilterError("A personal administrator identity is required.")
        if body is not None and (
            not isinstance(body, str) or not body or len(body) > 2000
        ):
            raise FilterError("Filter replies must contain 1–2000 characters.")
    db = getattr(ctx, "db", None)

    def update(stored):
        if body is None:
            return stored.pop(name, None) is not None
        if name not in stored and len(stored) >= 100:
            raise FilterError(
                "This group has 100 filters. Remove one before adding another; existing filters can still be updated."
            )
        stored[name] = body
        return True

    if db is None:
        stored = ctx.chats.filters(group_id)
        if name is None:
            return stored
        changed = update(stored)
        if body is None:
            ctx.chats.remove_filter(group_id, name)
        else:
            ctx.chats.set_filter(group_id, name, body, by=actor)
        return changed
    if not db.connected or getattr(db, "_pool", None) is None:
        raise FilterError("Database filters are unavailable. No changes confirmed.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for(f"filters:{group_id}"),
                    timeout=5,
                )
                row = await conn.fetchrow(
                    "SELECT payload,version FROM agent_group_filters WHERE tenant=$1 AND group_id=$2",
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
                    stored = (raw or {}).get(str(group_id), {}).get("settings", {}).get(
                        "filters", {}
                    ) or {}
                    if not isinstance(stored, dict) or any(
                        not isinstance(k, str) or not isinstance(v, str)
                        for k, v in stored.items()
                    ):
                        raise FilterError("Persisted legacy filters are invalid.")
                    payload = json.dumps(stored)
                    await conn.execute(
                        "INSERT INTO agent_group_filters(tenant,group_id,payload) VALUES($1,$2,$3)",
                        db.scope,
                        group_id,
                        payload,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_group_filter_revisions(tenant,group_id,version,payload,actor_id,operation) VALUES($1,$2,0,$3,0,'import')",
                        db.scope,
                        group_id,
                        payload,
                        timeout=5,
                    )
                    row = {"payload": payload, "version": 0}
                stored = json.loads(row["payload"])
                if name is None:
                    return stored
                changed = update(stored)
                if changed:
                    payload, version = json.dumps(stored), row["version"] + 1
                    await conn.execute(
                        "UPDATE agent_group_filters SET payload=$3,version=$4 WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        payload,
                        version,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_group_filter_revisions(tenant,group_id,version,payload,actor_id,operation) VALUES($1,$2,$3,$4,$5,$6)",
                        db.scope,
                        group_id,
                        version,
                        payload,
                        actor,
                        "remove" if body is None else "set",
                        timeout=5,
                    )
        return changed
    except FilterError:
        raise
    except Exception:
        raise FilterError(
            "Filters unavailable or result unconfirmed. Refresh before retrying."
        ) from None
