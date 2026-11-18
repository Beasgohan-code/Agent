"""Durable temporary-promotion intents, not a Telegram executor.

An unresolved intent blocks subsequent grants for that member. No command may be
registered until grant/demotion reconciliation is wired and verified end to end.
"""
import json
import uuid
from datetime import datetime,timezone

SCHEMA=(
    """CREATE TABLE IF NOT EXISTS agent_timed_promotions (
    tenant TEXT NOT NULL, id TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    target_id BIGINT NOT NULL CHECK(target_id>0), actor_id BIGINT NOT NULL CHECK(actor_id>0),
    bot_id BIGINT NOT NULL CHECK(bot_id>0), rights JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, state TEXT NOT NULL DEFAULT 'prepared'
    CHECK(state IN ('prepared','active','review','closed','cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,id))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS agent_timed_promotions_unresolved
    ON agent_timed_promotions(tenant,group_id,target_id)
    WHERE state NOT IN ('closed','cancelled')""",
    """CREATE INDEX IF NOT EXISTS agent_timed_promotions_due
    ON agent_timed_promotions(tenant,expires_at) WHERE state IN ('prepared','active')""",
)
# Explicitly limited, non-delegating group rights, matching normal /promote.
RIGHTS=frozenset(('can_manage_chat','can_delete_messages','can_manage_video_chats',
    'can_restrict_members','can_change_info','can_invite_users','can_pin_messages'))
TRANSITIONS={'prepared':{'active','review','cancelled'},'active':{'review','closed'},'review':{'closed'},'closed':set(),'cancelled':set()}


class PromotionError(RuntimeError):
    """Safe durable-intent failure. Never evidence of Telegram action."""


def pool(db):
    if db is None or not db.connected or getattr(db,'_pool',None) is None:
        raise PromotionError('Temporary promotions require available PostgreSQL.')
    return db._pool


def identity(value):
    return type(value) is int and 0<value<2**63


async def reserve(db,group,target,*,actor,bot,expires,rights):
    if (type(group) is not int or not -(2**63)<group<0 or not all(identity(v) for v in (target,actor,bot))
            or target==bot or not isinstance(rights,dict) or not rights or not set(rights)<=RIGHTS
            or any(type(v) is not bool for v in rights.values()) or not any(rights.values())):
        raise PromotionError('Invalid temporary promotion identity or limited rights.')
    if not isinstance(expires,datetime) or expires.tzinfo is None or expires.utcoffset() is None:
        raise PromotionError('An aware promotion deadline is required.')
    seconds=(expires-datetime.now(timezone.utc)).total_seconds()
    if not 60<=seconds<=366*86400:
        raise PromotionError('Temporary promotion duration must be 1 minute–366 days.')
    connection_pool=pool(db)
    request=uuid.uuid4().hex
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            await conn.execute('''INSERT INTO agent_timed_promotions
                (tenant,id,group_id,target_id,actor_id,bot_id,rights,expires_at)
                VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8)''',
                db.scope,request,group,target,actor,bot,json.dumps(rights),expires,timeout=5)
        return request
    except Exception:
        raise PromotionError('Promotion admission unconfirmed or member has an unresolved intent. Inspect durable state before retrying.') from None


async def read(db,request,*,group=None):
    connection_pool=pool(db)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            row=await conn.fetchrow('''SELECT * FROM agent_timed_promotions WHERE tenant=$1 AND id=$2
                AND ($3::bigint IS NULL OR group_id=$3)''',db.scope,request,group,timeout=5)
        result=dict(row) if row else None
        if result is not None and isinstance(result['rights'],str):
            result['rights']=json.loads(result['rights'])
        return result
    except Exception:
        raise PromotionError('Promotion intent read unavailable.') from None


async def finish(db,request,state,*,expected):
    if expected not in TRANSITIONS or state not in TRANSITIONS[expected]:
        raise PromotionError('Invalid promotion intent transition.')
    connection_pool=pool(db)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            changed=await conn.fetchval('''UPDATE agent_timed_promotions SET state=$3,updated_at=now()
                WHERE tenant=$1 AND id=$2 AND state=$4 RETURNING id''',db.scope,request,state,expected,timeout=5)
        if changed is None:
            raise PromotionError('Promotion intent changed or unavailable; stale update refused.')
    except PromotionError:
        raise
    except Exception:
        raise PromotionError('Promotion intent update unconfirmed. Inspect durable state before retrying.') from None
