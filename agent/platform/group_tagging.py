"""Canonical opt-in mention registry. No scraping, inferred consent or presence claims."""
SCHEMA=(
    """CREATE TABLE IF NOT EXISTS agent_tag_settings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), enabled BOOLEAN NOT NULL DEFAULT false,
    updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_tag_members (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, user_id BIGINT NOT NULL CHECK(user_id>0),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,user_id),
    FOREIGN KEY(tenant,group_id) REFERENCES agent_tag_settings(tenant,group_id))""",
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
                    await conn.execute('DELETE FROM agent_tag_members WHERE tenant=$1 AND group_id=$2 AND user_id=$3',db.scope,group,user,timeout=5)
                    count-=int(exists)
                    exists=False
        return {'enabled':current,'count':count,'joined':exists}
    except TagError:
        raise
    except Exception:
        raise TagError('Tagging read or change unconfirmed. Reopen /allsettings before retrying.') from None
