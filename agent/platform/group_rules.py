"""Canonical group rules with immutable per-group revisions and awaited commits."""

import json

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_group_rules (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
        body TEXT NOT NULL, version BIGINT NOT NULL DEFAULT 0,
        updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_group_rule_revisions (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
        body TEXT NOT NULL, actor_id BIGINT NOT NULL, operation TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,version),
        FOREIGN KEY(tenant,group_id) REFERENCES agent_group_rules(tenant,group_id))""",
)


class RulesError(RuntimeError):
    """Rules could not be read or committed authoritatively."""


async def _operate(ctx, group_id, body=None, actor=None):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise RulesError("Rules belong to a group.")
    if body is not None and (not isinstance(body, str) or len(body) > 3000):
        raise RulesError("Rules must be at most 3000 characters.")
    if body is not None and (type(actor) is not int or not 0 < actor < 2**63):
        raise RulesError("A personal administrator identity is required.")
    db = getattr(ctx, "db", None)
    if db is None:
        if body is not None:
            ctx.chats.put(group_id, "rules", body)
            ctx.chats.log(
                group_id,
                "rules:set" if body else "rules:clear",
                actor_id=actor,
                reason=f"{len(body)} chars",
            )
        return {"body": ctx.chats.get(group_id, "rules", "") or "", "version": 0}
    if not db.connected or getattr(db, "_pool", None) is None:
        raise RulesError("Database rules are unavailable. No changes confirmed.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                if body is not None:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        db.name_for(f"rules:{group_id}"),
                        timeout=5,
                    )
                row = await conn.fetchrow(
                    "SELECT body,version FROM agent_group_rules WHERE tenant=$1 AND group_id=$2",
                    db.scope,
                    group_id,
                    timeout=5,
                )
                if row is None:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        db.name_for(f"rules:{group_id}"),
                        timeout=5,
                    )
                    row = await conn.fetchrow(
                        "SELECT body,version FROM agent_group_rules WHERE tenant=$1 AND group_id=$2",
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
                        legacy = (raw or {}).get(str(group_id), {}).get(
                            "settings", {}
                        ).get("rules", "") or ""
                        if not isinstance(legacy, str):
                            raise RulesError("Persisted legacy rules are invalid.")
                        await conn.execute(
                            "INSERT INTO agent_group_rules(tenant,group_id,body,updated_by) VALUES($1,$2,$3,0)",
                            db.scope,
                            group_id,
                            legacy,
                            timeout=5,
                        )
                        await conn.execute(
                            "INSERT INTO agent_group_rule_revisions(tenant,group_id,version,body,actor_id,operation) VALUES($1,$2,0,$3,0,'import')",
                            db.scope,
                            group_id,
                            legacy,
                            timeout=5,
                        )
                        row = {"body": legacy, "version": 0}
                result = dict(row)
                if body is not None:
                    result = {"body": body, "version": row["version"] + 1}
                    await conn.execute(
                        "UPDATE agent_group_rules SET body=$3,version=$4,updated_by=$5,updated_at=now() WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        body,
                        result["version"],
                        actor,
                        timeout=5,
                    )
                    await conn.execute(
                        "INSERT INTO agent_group_rule_revisions(tenant,group_id,version,body,actor_id,operation) VALUES($1,$2,$3,$4,$5,$6)",
                        db.scope,
                        group_id,
                        result["version"],
                        body,
                        actor,
                        "set" if body else "clear",
                        timeout=5,
                    )
        return result
    except RulesError:
        raise
    except Exception:
        raise RulesError(
            "Rules result not confirmed. Refresh before retrying."
        ) from None


async def read_rules(ctx, group_id):
    return await _operate(ctx, group_id)


async def save_rules(ctx, group_id, body, *, actor):
    return await _operate(ctx, group_id, body, actor)


def message_chunks(text, limit=3000):
    """Split on Unicode codepoints while respecting Telegram UTF-16 budgets."""
    if not 2 <= limit <= 3000:
        raise ValueError("Invalid rules chunk limit")
    current, units = [], 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > limit:
            yield "".join(current)
            current, units = [], 0
        current.append(char)
        units += size
    if current:
        yield "".join(current)


async def rules_history(ctx, group_id):
    """Recent committed administrator changes for /modlog; imports are excluded."""
    db = getattr(ctx, "db", None)
    if db is None:
        return []
    if not db.connected or getattr(db, "_pool", None) is None:
        raise RulesError("Rule history unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(
                """SELECT version,actor_id,operation,extract(epoch from created_at) AS at
                FROM agent_group_rule_revisions WHERE tenant=$1 AND group_id=$2 AND actor_id>0
                ORDER BY version DESC LIMIT 10""",
                db.scope,
                group_id,
                timeout=5,
            )
        return [
            {
                "action": "rules:" + row["operation"],
                "actor": row["actor_id"],
                "at": float(row["at"]),
                "reason": f"revision {row['version']} · by {row['actor_id']}",
            }
            for row in rows
        ]
    except Exception:
        raise RulesError("Rule history unavailable.") from None
