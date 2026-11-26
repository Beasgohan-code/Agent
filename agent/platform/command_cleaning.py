"""Canonical opt-in command-message cleaning with transactional setting revisions."""

import json

KINDS = ("known",)
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_command_cleaning (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    kinds JSONB NOT NULL, version BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_command_cleaning_revisions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
    kinds JSONB NOT NULL, actor_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,group_id,version), FOREIGN KEY(tenant,group_id)
    REFERENCES agent_command_cleaning(tenant,group_id))""",
)


class CleaningError(RuntimeError):
    """Cleaning settings unavailable or invalid; no mutation confirmed."""


async def _operate(ctx, group, kinds=None, *, actor=None):
    if type(group) is not int or not -(2**63) < group < 0:
        raise CleaningError("Command cleaning belongs to a group.")
    if kinds is not None:
        if type(actor) is not int or not 0 < actor < 2**63:
            raise CleaningError("A personal administrator identity is required.")
        if (
            not isinstance(kinds, (list, tuple))
            or len(kinds) > len(KINDS)
            or any(not isinstance(k, str) or k not in KINDS for k in kinds)
        ):
            raise CleaningError("Choose known-command cleaning on or off.")
        kinds = sorted(set(kinds))
    db = getattr(ctx, "db", None)
    if db is None:
        if kinds is not None:
            ctx.chats.put(group, "command_cleaning", list(kinds))
            ctx.chats.log(
                group,
                "cleancommand:settings",
                actor_id=actor,
                reason=",".join(kinds) or "off",
            )
        return list(ctx.chats.get(group, "command_cleaning", []))
    if not db.connected or getattr(db, "_pool", None) is None:
        raise CleaningError(
            "Database cleaning settings unavailable. No changes confirmed."
        )
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for(f"command-cleaning:{group}"),
                    timeout=5,
                )
                row = await conn.fetchrow(
                    "SELECT kinds,version FROM agent_command_cleaning WHERE tenant=$1 AND group_id=$2",
                    db.scope,
                    group,
                    timeout=5,
                )
                if kinds is None:
                    return (
                        (
                            json.loads(row["kinds"])
                            if isinstance(row["kinds"], str)
                            else row["kinds"]
                        )
                        if row
                        else []
                    )
                version = row["version"] + 1 if row else 1
                payload = json.dumps(kinds)
                await conn.execute(
                    """INSERT INTO agent_command_cleaning(tenant,group_id,kinds,version) VALUES($1,$2,$3::jsonb,$4)
                    ON CONFLICT(tenant,group_id) DO UPDATE SET kinds=EXCLUDED.kinds,version=EXCLUDED.version""",
                    db.scope,
                    group,
                    payload,
                    version,
                    timeout=5,
                )
                await conn.execute(
                    """INSERT INTO agent_command_cleaning_revisions(tenant,group_id,version,kinds,actor_id)
                    VALUES($1,$2,$3,$4::jsonb,$5)""",
                    db.scope,
                    group,
                    version,
                    payload,
                    actor,
                    timeout=5,
                )
        return kinds
    except Exception:
        raise CleaningError(
            "Cleaning setting result unconfirmed. Refresh before retrying."
        ) from None


async def operate(ctx, group, enabled=None, *, actor=None):
    if enabled is not None and type(enabled) is not bool:
        raise CleaningError("Choose on or off.")
    result = await _operate(
        ctx,
        group,
        None if enabled is None else (["known"] if enabled else []),
        actor=actor,
    )
    return "known" in result
