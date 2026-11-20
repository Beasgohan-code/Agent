"""Awaited intent/outcome records for new manual restriction variants.

Telegram side effects cannot be transacted with SQL. Pending records deliberately
remain pending after a crash; replaying the same command never retries the action.
"""

import uuid

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_restriction_cases (
    tenant TEXT NOT NULL, id UUID NOT NULL, chat_id BIGINT NOT NULL CHECK(chat_id<0),
    message_id BIGINT NOT NULL CHECK(message_id>0), actor_id BIGINT NOT NULL CHECK(actor_id>0),
    target_id BIGINT NOT NULL CHECK(target_id>0), action TEXT NOT NULL,
    seconds BIGINT NOT NULL, reason TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending'
    CHECK(outcome IN ('pending','applied','partial','unconfirmed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,id), UNIQUE(tenant,chat_id,message_id))""",
)


class CaseError(RuntimeError):
    """Restriction intent or outcome could not be confirmed."""


def pool(ctx):
    db = getattr(ctx, "db", None)
    if db is not None and (not db.connected or getattr(db, "_pool", None) is None):
        raise CaseError("Moderation database unavailable. No new action attempted.")
    return db


async def begin(ctx, chat, message, actor, target, action, seconds, reason):
    if (
        type(chat) is not int
        or not -(2**63) < chat < 0
        or any(
            type(v) is not int or not 0 < v < 2**63 for v in (message, actor, target)
        )
    ):
        raise CaseError("Valid personal identities and a group message are required.")
    if (
        action
        not in (
            "dwarn",
            "swarn",
            "tban",
            "tmute",
            "dban",
            "dmute",
            "dkick",
            "sban",
            "smute",
            "skick",
            "kickme",
        )
        or type(seconds) is not int
        or not 0 <= seconds <= 365 * 86400
        or not isinstance(reason, str)
        or len(reason) > 1000
    ):
        raise CaseError("Invalid restriction details.")
    db = pool(ctx)
    identity = uuid.uuid4()
    if db is None:
        return identity
    try:
        async with db._pool.acquire(timeout=5) as conn:
            inserted = await conn.fetchval(
                """INSERT INTO agent_restriction_cases(tenant,id,chat_id,message_id,actor_id,target_id,action,seconds,reason)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(tenant,chat_id,message_id) DO NOTHING RETURNING id""",
                db.scope,
                identity,
                chat,
                message,
                actor,
                target,
                action,
                seconds,
                reason,
                timeout=5,
            )
        if inserted is None:
            raise CaseError(
                "This command was already attempted. Check current Telegram state; it was not retried."
            )
        return identity
    except CaseError:
        raise
    except Exception:
        raise CaseError(
            "Moderation intent not confirmed. No new action attempted."
        ) from None


async def finish(ctx, identity, outcome):
    if outcome not in ("applied", "partial", "unconfirmed"):
        raise CaseError("Invalid moderation outcome.")
    db = pool(ctx)
    if db is None:
        return
    try:
        async with db._pool.acquire(timeout=5) as conn:
            result = await conn.fetchval(
                """UPDATE agent_restriction_cases SET outcome=$3,updated_at=now()
                WHERE tenant=$1 AND id=$2 AND outcome='pending' RETURNING id""",
                db.scope,
                identity,
                outcome,
                timeout=5,
            )
        if result is None:
            raise CaseError("Moderation outcome was not recorded.")
    except Exception:
        raise CaseError(
            "Moderation outcome recording unavailable. Check Telegram state before retrying."
        ) from None


async def history(ctx, chat):
    db = pool(ctx)
    if db is None:
        return []
    try:
        async with db._pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(
                """SELECT action,outcome,actor_id,target_id,reason,extract(epoch from created_at) AS at
                FROM agent_restriction_cases WHERE tenant=$1 AND chat_id=$2 ORDER BY created_at DESC,id DESC LIMIT 10""",
                db.scope,
                chat,
                timeout=5,
            )
        return [
            {
                "action": r["action"] + ":" + r["outcome"],
                "actor": r["actor_id"],
                "target": r["target_id"],
                "reason": r["reason"] or "no reason",
                "at": float(r["at"]),
            }
            for r in rows
        ]
    except Exception:
        raise CaseError("Restriction history unavailable.") from None
