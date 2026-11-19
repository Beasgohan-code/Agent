"""Awaited, tenant-scoped greeting destination with atomic revision history."""

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_action_topics (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    topic_id BIGINT NOT NULL CHECK(topic_id>0 AND topic_id<2147483648),
    version BIGINT NOT NULL, PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_action_topic_revisions (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, version BIGINT NOT NULL,
    topic_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,version),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_action_topics(tenant,group_id))""",
)


class ActionTopicError(RuntimeError):
    """Topic destination unavailable; do not reroute into a different thread."""


async def operate(ctx, group, topic=None, *, actor=None):
    if type(group) is not int or not -(2**63) < group < 0:
        raise ActionTopicError("An action topic belongs to a group.")
    if topic is not None and (
        type(topic) is not int
        or not 0 < topic < 2**31
        or type(actor) is not int
        or not 0 < actor < 2**63
    ):
        raise ActionTopicError(
            "A valid topic and personal administrator identity are required."
        )
    db = getattr(ctx, "db", None)
    if db is None:
        if topic is not None:
            ctx.chats.put(group, "action_topic", topic)
            ctx.chats.log(group, "setactiontopic", actor_id=actor, reason=str(topic))
        return ctx.chats.get(group, "action_topic", None)
    if not db.connected or getattr(db, "_pool", None) is None:
        raise ActionTopicError(
            "Database action-topic settings unavailable. No destination confirmed."
        )
    try:
        async with db._pool.acquire(timeout=5) as conn:
            if topic is None:
                return await conn.fetchval(
                    "SELECT topic_id FROM agent_action_topics WHERE tenant=$1 AND group_id=$2",
                    db.scope,
                    group,
                    timeout=5,
                )
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    db.name_for(f"action-topic:{group}"),
                    timeout=5,
                )
                version = await conn.fetchval(
                    """INSERT INTO agent_action_topics(tenant,group_id,topic_id,version) VALUES($1,$2,$3,1)
                    ON CONFLICT(tenant,group_id) DO UPDATE SET topic_id=EXCLUDED.topic_id,version=agent_action_topics.version+1 RETURNING version""",
                    db.scope,
                    group,
                    topic,
                    timeout=5,
                )
                await conn.execute(
                    """INSERT INTO agent_action_topic_revisions(tenant,group_id,version,topic_id,actor_id) VALUES($1,$2,$3,$4,$5)""",
                    db.scope,
                    group,
                    version,
                    topic,
                    actor,
                    timeout=5,
                )
        return topic
    except Exception:
        raise ActionTopicError(
            "Action-topic setting result unconfirmed. Refresh before retrying."
        ) from None
