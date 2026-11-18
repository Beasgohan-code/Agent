"""Canonical opt-in mention registry. No scraping, inferred consent or presence claims."""
import uuid

SCHEMA=(
    """CREATE TABLE IF NOT EXISTS agent_tag_settings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), enabled BOOLEAN NOT NULL DEFAULT false,
    updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_tag_members (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, user_id BIGINT NOT NULL CHECK(user_id>0),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,user_id),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_tag_settings(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_tag_runs (
    tenant TEXT NOT NULL, id TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    actor_id BIGINT NOT NULL CHECK(actor_id>0), members BIGINT[] NOT NULL,
    total INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN ('paused','sending','review','completed','stopped')),
    last_attempt_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,id))""",
    """ALTER TABLE agent_tag_runs ADD COLUMN IF NOT EXISTS style TEXT NOT NULL DEFAULT 'plain'
    CHECK(style IN ('plain','emoji'))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS agent_tag_runs_open ON agent_tag_runs(tenant,group_id)
    WHERE state IN ('paused','sending','review')""",

)


class TagError(RuntimeError):
    """Safe tagging validation/storage failure."""


def personal(value):
    return type(value) is int and 0<value<2**63


async def operate(db,group,*,enabled=None,actor=None,join=None,user=None):
    if type(group) is not int or not -(2**63)<group<0:
        raise TagError('Tagging settings belong to a group.')
    if enabled is not None and (type(enabled) is not bool or not personal(actor)):
        raise TagError('A personal administrator and on/off setting are required.')
    if user is not None and not personal(user):
        raise TagError('Use your personal identity.')
    if join is not None and (type(join) is not bool or not personal(user) or enabled is not None):
        raise TagError('Invalid personal opt-in request.')
    if db is None or not db.connected or getattr(db,'_pool',None) is None:
        raise TagError('PostgreSQL tagging storage unavailable. No change confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'tagging:{group}'),timeout=5)
                await conn.execute('INSERT INTO agent_tag_settings(tenant,group_id,updated_by) VALUES($1,$2,0) ON CONFLICT DO NOTHING',db.scope,group,timeout=5)
                current=await conn.fetchval('SELECT enabled FROM agent_tag_settings WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                if enabled is not None:
                    current=enabled
                    await conn.execute('UPDATE agent_tag_settings SET enabled=$3,updated_by=$4,updated_at=now() WHERE tenant=$1 AND group_id=$2',db.scope,group,enabled,actor,timeout=5)
                    if not enabled:
                        await conn.execute("UPDATE agent_tag_runs SET state='stopped',members='{}' WHERE tenant=$1 AND group_id=$2",db.scope,group,timeout=5)
                        await conn.execute('DELETE FROM agent_tag_members WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                exists=await conn.fetchval('SELECT EXISTS(SELECT 1 FROM agent_tag_members WHERE tenant=$1 AND group_id=$2 AND user_id=$3)',db.scope,group,user or 0,timeout=5)
                count=await conn.fetchval('SELECT count(*) FROM agent_tag_members WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                if join is True:
                    if not current:
                        raise TagError('Opt-in mentions are off in this group.')
                    if not exists and count>=500:
                        raise TagError('This group has reached the 500-member opt-in limit.')
                    await conn.execute('INSERT INTO agent_tag_members(tenant,group_id,user_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',db.scope,group,user,timeout=5)
                    count+=int(not exists)
                    exists=True
                elif join is False:
                    await conn.execute("UPDATE agent_tag_runs SET members=array_replace(members,$3::bigint,0::bigint) WHERE tenant=$1 AND group_id=$2",db.scope,group,user,timeout=5)
                    await conn.execute('DELETE FROM agent_tag_members WHERE tenant=$1 AND group_id=$2 AND user_id=$3',db.scope,group,user,timeout=5)
                    count-=int(exists)
                    exists=False
        return {'enabled':current,'count':count,'joined':exists}
    except TagError:
        raise
    except Exception:
        raise TagError('Tagging read or change unconfirmed. Reopen /allsettings before retrying.') from None


def _pool(db,group,actor):
    if type(group) is not int or not -(2**63)<group<0 or not personal(actor):
        raise TagError('Personal administrator and group required.')
    if db is None or not db.connected or getattr(db,'_pool',None) is None:
        raise TagError('PostgreSQL tagging storage unavailable.')
    return db._pool


async def start_run(db,group,*,actor,style="plain"):
    if style not in ('plain','emoji'):
        raise TagError('Invalid mention style.')
    connection_pool=_pool(db,group,actor)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'tagging:{group}'),timeout=5)
                enabled=await conn.fetchval('SELECT enabled FROM agent_tag_settings WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                if enabled is not True:
                    raise TagError('Opt-in mentions are off. Use /allsettings on first.')
                members=await conn.fetch('SELECT user_id FROM agent_tag_members WHERE tenant=$1 AND group_id=$2 ORDER BY user_id LIMIT 501',db.scope,group,timeout=5)
                if not 1<=len(members)<=500:
                    raise TagError('A run requires 1–500 opted-in members.')
                if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM agent_tag_runs WHERE tenant=$1 AND group_id=$2 AND state IN ('paused','sending','review'))",db.scope,group,timeout=5):
                    raise TagError('A mention run is open. Use its Resume/Stop buttons or /tagabort.')
                request=uuid.uuid4().hex
                await conn.execute("INSERT INTO agent_tag_runs(tenant,id,group_id,actor_id,members,total,state,style) VALUES($1,$2,$3,$4,$5,$6,'paused',$7)",db.scope,request,group,actor,[r['user_id'] for r in members],len(members),style,timeout=5)
        return request
    except TagError:
        raise
    except Exception:
        raise TagError('Run admission unconfirmed. Use /tagabort before starting another run.') from None


async def claim_batch(db,group,request,*,actor):
    connection_pool=_pool(db,group,actor)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'tagging:{group}'),timeout=5)
                row=await conn.fetchrow('SELECT * FROM agent_tag_runs WHERE tenant=$1 AND id=$2 AND group_id=$3 FOR UPDATE',db.scope,request,group,timeout=5)
                if row is None or row['state']!='paused':
                    raise TagError('Run is stopped, complete, busy or uncertain. No batch retried.')
                enabled=await conn.fetchval('SELECT enabled FROM agent_tag_settings WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                if not enabled:
                    raise TagError('Opt-in mentions are off.')
                if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM agent_tag_runs WHERE tenant=$1 AND group_id=$2 AND last_attempt_at>now()-interval '30 seconds')",db.scope,group,timeout=5):
                    raise TagError('Wait 30 seconds between batches in this group.')
                next_cursor=min(row['cursor']+5,row['total'])
                selected=row['members'][row['cursor']:next_cursor]
                opted=await conn.fetch('SELECT user_id FROM agent_tag_members WHERE tenant=$1 AND group_id=$2 AND user_id=ANY($3::bigint[]) ORDER BY user_id',db.scope,group,selected,timeout=5)
                await conn.execute("UPDATE agent_tag_runs SET state='sending',cursor=$3,last_attempt_at=now() WHERE tenant=$1 AND id=$2",db.scope,request,next_cursor,timeout=5)
        return {'members':[r['user_id'] for r in opted],'cursor':next_cursor,'total':row['total'],'style':row['style']}
    except TagError:
        raise
    except Exception:
        raise TagError('Batch claim unconfirmed. No automatic retry; use /tagabort.') from None


async def settle_batch(db,group,request,*,confirmed):
    connection_pool=_pool(db,group,1)
    if type(confirmed) is not bool:
        raise TagError('Invalid batch acknowledgement.')
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            state=await conn.fetchval("""UPDATE agent_tag_runs SET state=CASE WHEN NOT $4 THEN 'review'
                WHEN cursor>=total THEN 'completed' ELSE 'paused' END,
                members=CASE WHEN $4 AND cursor>=total THEN '{}'::bigint[] ELSE members END
                WHERE tenant=$1 AND id=$2 AND group_id=$3 AND state='sending' RETURNING state""",db.scope,request,group,confirmed,timeout=5)
        return state or 'stopped'
    except Exception:
        raise TagError('Batch outcome unconfirmed. No automatic retry; use /tagabort.') from None


async def stop_run(db,group,*,actor,request=None):
    connection_pool=_pool(db,group,actor)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'tagging:{group}'),timeout=5)
                rows=await conn.fetch("""UPDATE agent_tag_runs SET state='stopped',members='{}' WHERE tenant=$1 AND group_id=$2
                    AND ($3::text IS NULL OR id=$3) AND state IN ('paused','sending','review') RETURNING id""",db.scope,group,request,timeout=5)
        return len(rows)
    except Exception:
        raise TagError('Stop unconfirmed. Check /allsettings before retrying.') from None


async def eligible(db,group,request,members):
    """Last pre-send consent/enable/run check; no cached roster is authoritative."""
    connection_pool=_pool(db,group,1)
    try:
        async with connection_pool.acquire(timeout=5) as conn:
            rows=await conn.fetch("""SELECT m.user_id FROM agent_tag_members m JOIN agent_tag_settings s
                USING(tenant,group_id) JOIN agent_tag_runs r USING(tenant,group_id)
                WHERE m.tenant=$1 AND m.group_id=$2 AND r.id=$3 AND r.state='sending'
                AND s.enabled AND m.user_id=ANY($4::bigint[]) ORDER BY m.user_id""",db.scope,group,request,members,timeout=5)
        return [row['user_id'] for row in rows]
    except Exception:
        raise TagError('Final consent check unavailable. No batch should be sent.') from None
