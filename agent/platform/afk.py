"""Current AFK status only; no message-content or presence tracking."""
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_afk (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), user_id BIGINT NOT NULL CHECK(user_id>0),
    reason TEXT NOT NULL CHECK(length(reason)<=500), since TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_notice TIMESTAMPTZ, PRIMARY KEY(tenant,group_id,user_id))""",
    """CREATE TABLE IF NOT EXISTS agent_afk_requests (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,group_id,user_id,message_id))""",
)


class AFKError(RuntimeError):
    """Safe AFK storage status; no raw database/provider errors."""


def database(ctx, group, user):
    if type(group) is not int or not -(2**63)<group<0 or type(user) is not int or not 0<user<2**63:
        raise AFKError('A group and personal user identity are required.')
    db=getattr(ctx,'db',None)
    if db is None or not db.connected or getattr(db,'_pool',None) is None:
        raise AFKError('PostgreSQL AFK storage unavailable. No status change confirmed.')
    return db


async def toggle(ctx, group, user, message, reason):
    db=database(ctx,group,user)
    if type(message) is not int or not 0<message<2**63 or not isinstance(reason,str) or len(reason)>500:
        raise AFKError('A valid message identity and reason of at most 500 characters are required.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'afk:{group}:{user}'),timeout=5)
                inserted=await conn.fetchval('INSERT INTO agent_afk_requests(tenant,group_id,user_id,message_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING message_id',db.scope,group,user,message,timeout=5)
                if inserted is None:
                    raise AFKError('This AFK request was already processed. Status was not toggled again.')
                removed=await conn.fetchval('DELETE FROM agent_afk WHERE tenant=$1 AND group_id=$2 AND user_id=$3 RETURNING user_id',db.scope,group,user,timeout=5)
                if removed is not None:
                    return False
                await conn.execute('INSERT INTO agent_afk(tenant,group_id,user_id,reason) VALUES($1,$2,$3,$4)',db.scope,group,user,reason,timeout=5)
        return True
    except AFKError:
        raise
    except Exception:
        raise AFKError('AFK update unconfirmed. No automatic retry; inspect your status before sending a new toggle.') from None


async def clear(ctx, group, user):
    db=database(ctx,group,user)
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'afk:{group}:{user}'),timeout=5)
                result=await conn.fetchval('DELETE FROM agent_afk WHERE tenant=$1 AND group_id=$2 AND user_id=$3 RETURNING user_id',db.scope,group,user,timeout=5)
        return result is not None
    except Exception:
        raise AFKError('AFK return update unconfirmed.') from None


async def notice(ctx, group, user):
    db=database(ctx,group,user)
    try:
        async with db._pool.acquire(timeout=5) as conn:
            row=await conn.fetchrow("UPDATE agent_afk SET last_notice=now() WHERE tenant=$1 AND group_id=$2 AND user_id=$3 AND (last_notice IS NULL OR last_notice<now()-interval '30 seconds') RETURNING reason,extract(epoch from now()-since) AS seconds",db.scope,group,user,timeout=5)
        return dict(row) if row else None
    except Exception:
        raise AFKError('AFK notification lookup unavailable.') from None
