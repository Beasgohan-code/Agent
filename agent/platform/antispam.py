"""Awaited, per-group protection policies with transactional change history.

JSONB holds flexible policy settings; tenant/group keys and audit rows are
relational. Legacy settings are imported from SQL on first access; system imports use
updated_by=0. Active older writers must be quiesced during rollout.
"""

import copy
import json

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_antispam_policies (
        tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
        policy JSONB NOT NULL, updated_by BIGINT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_antispam_history (
        id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, group_id BIGINT NOT NULL,
        actor_id BIGINT NOT NULL, operation TEXT NOT NULL, policy JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE INDEX IF NOT EXISTS agent_antispam_history_group
        ON agent_antispam_history(tenant,group_id,id DESC)""",
)
FLAGS = (
    "flood_enabled",
    "duplicate_enabled",
    "links_enabled",
    "invites_enabled",
    "keywords_enabled",
)


class PolicyError(RuntimeError):
    """A protection-policy read or change was not confirmed."""


def _apply(policy, operation, value):
    work = copy.deepcopy(policy)
    if operation in ("on", "off"):
        for flag in FLAGS if operation == "off" else FLAGS[:4]:
            work[flag] = operation == "on"
        if operation == "on":
            work["keywords_enabled"] = bool(work.get("blocked_keywords"))
    elif operation in ("links", "invites", "flood", "duplicates") and value in (
        "on",
        "off",
    ):
        key = {
            "links": "links_enabled",
            "invites": "invites_enabled",
            "flood": "flood_enabled",
            "duplicates": "duplicate_enabled",
        }[operation]
        work[key] = value == "on"
    elif operation == "action" and value in ("delete", "warn", "mute", "kick", "ban"):
        work["action"] = value
    elif (
        operation in ("limit", "mute")
        and isinstance(value, str)
        and value.isdigit()
        and len(value) <= 9
    ):
        work["flood_messages" if operation == "limit" else "mute_seconds"] = min(
            1000 if operation == "limit" else 366 * 86400,
            max(2 if operation == "limit" else 30, int(value)),
        )
    elif (
        operation in ("keyword", "keywords")
        and isinstance(value, str)
        and 0 < len(value) <= 200
    ):
        words = list(dict.fromkeys([*work["blocked_keywords"], value.lower()]))
        if len(words) > 100:
            raise PolicyError("At most 100 blocked phrases are supported.")
        work["blocked_keywords"] = words
        work["keywords_enabled"] = True
    elif operation == "keyword-clear":
        work["blocked_keywords"] = []
        work["keywords_enabled"] = False
    else:
        raise PolicyError(
            "Usage: /antispam on|off|limit 7|action mute|links off|invites off|flood on|duplicates on|mute 300|keyword phrase|keyword-clear"
        )
    return work


def _decoded(raw):
    return json.loads(raw) if isinstance(raw, str) else raw


async def _legacy(conn, db, group_id):
    from .chats import DEFAULT_ANTISPAM

    raw = (
        _decoded(
            await conn.fetchval(
                "SELECT value FROM agent_documents WHERE name=$1",
                db.name_for("chats"),
                timeout=5,
            )
        )
        or {}
    )
    stored = raw.get(str(group_id), {}).get("settings", {}).get("antispam", {})
    return {**copy.deepcopy(DEFAULT_ANTISPAM), **stored}


async def _operate(ctx, group_id, operation=None, value=None, actor=None):
    if type(group_id) is not int or not -(2**63) < group_id < 0:
        raise PolicyError("Protection settings require a group.")
    if operation is not None and (type(actor) is not int or not 0 < actor < 2**63):
        raise PolicyError("A personal administrator identity is required.")
    db = getattr(ctx, "db", None)
    if db is None:
        policy = ctx.chats.antispam(group_id)
        if not operation:
            return policy
        updated = ctx.chats.save_antispam(group_id, _apply(policy, operation, value))
        ctx.chats.log(group_id, "antispam", actor_id=actor, reason=operation)
        return updated
    if not db.connected or getattr(db, "_pool", None) is None:
        raise PolicyError("PostgreSQL protection settings unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                if operation:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        db.name_for(f"antispam:{group_id}"),
                        timeout=5,
                    )
                policy = _decoded(
                    await conn.fetchval(
                        "SELECT policy FROM agent_antispam_policies WHERE tenant=$1 AND group_id=$2",
                        db.scope,
                        group_id,
                        timeout=5,
                    )
                )
                if policy is None:
                    # A first read imports once instead of rereading a potentially
                    # large legacy chat document for every incoming message.
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                        db.name_for(f"antispam:{group_id}"),
                        timeout=5,
                    )
                    policy = _decoded(
                        await conn.fetchval(
                            "SELECT policy FROM agent_antispam_policies WHERE tenant=$1 AND group_id=$2",
                            db.scope,
                            group_id,
                            timeout=5,
                        )
                    )
                    if policy is None:
                        policy = await _legacy(conn, db, group_id)
                        await conn.execute(
                            "INSERT INTO agent_antispam_policies(tenant,group_id,policy,updated_by) VALUES($1,$2,$3::jsonb,0)",
                            db.scope,
                            group_id,
                            json.dumps(policy),
                            timeout=5,
                        )
                if operation:
                    policy = _apply(policy, operation, value)
                    payload = json.dumps(policy)
                    await conn.execute(
                        """INSERT INTO agent_antispam_policies(tenant,group_id,policy,updated_by)
                        VALUES($1,$2,$3::jsonb,$4) ON CONFLICT(tenant,group_id) DO UPDATE
                        SET policy=EXCLUDED.policy,updated_by=EXCLUDED.updated_by,updated_at=now()""",
                        db.scope,
                        group_id,
                        payload,
                        actor,
                        timeout=5,
                    )
                    await conn.execute(
                        """INSERT INTO agent_antispam_history(tenant,group_id,actor_id,operation,policy)
                        VALUES($1,$2,$3,$4,$5::jsonb)""",
                        db.scope,
                        group_id,
                        actor,
                        operation,
                        payload,
                        timeout=5,
                    )
        return policy
    except PolicyError:
        raise
    except Exception:
        raise PolicyError(
            "Protection settings result not confirmed. Refresh before retrying."
        ) from None


async def read_policy(ctx, group_id):
    return await _operate(ctx, group_id)


async def change_policy(ctx, group_id, operation, value=None, *, actor):
    return await _operate(ctx, group_id, operation, value, actor)


async def policy_history(ctx, group_id):
    """Recent committed protection changes for the existing moderation log."""
    db = getattr(ctx, "db", None)
    if db is None:
        return []  # standalone changes already use the legacy log
    if not db.connected or getattr(db, "_pool", None) is None:
        raise PolicyError("Protection history unavailable.")
    try:
        async with db._pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(
                """SELECT actor_id,operation,extract(epoch from created_at) AS at
                FROM agent_antispam_history WHERE tenant=$1 AND group_id=$2 ORDER BY id DESC LIMIT 10""",
                db.scope,
                group_id,
                timeout=5,
            )
        return [
            {
                "action": "antispam",
                "actor": row["actor_id"],
                "at": float(row["at"]),
                "reason": f"{row['operation']} · by {row['actor_id']}",
            }
            for row in rows
        ]
    except Exception:
        raise PolicyError("Protection history unavailable.") from None
