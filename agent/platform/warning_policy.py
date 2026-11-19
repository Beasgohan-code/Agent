"""Canonical warning escalation configuration; one serialized policy per group."""
import json

SCHEMA=(
    """CREATE TABLE IF NOT EXISTS agent_warning_policies (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), policy JSONB NOT NULL,
    PRIMARY KEY(tenant,group_id))""",
    """CREATE TABLE IF NOT EXISTS agent_warning_policy_history (
    id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, group_id BIGINT NOT NULL,
    actor_id BIGINT NOT NULL, policy JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
)
DEFAULT={'limit':3,'action':'mute','expiry_seconds':0}


class PolicyError(RuntimeError):
    """Safe failure; no unconfirmed policy may become authoritative locally."""


def validate(policy):
    policy={**{'expiry_seconds':0},**policy}
    if (set(policy)!=set(DEFAULT) or type(policy['limit']) is not int or not 0<=policy['limit']<=20
            or policy['action'] not in ('mute','kick','ban') or type(policy['expiry_seconds']) is not int
            or not (policy['expiry_seconds']==0 or 60<=policy['expiry_seconds']<=366*86400)):
        raise PolicyError('Invalid warning policy: limit 0–20, mode mute|kick|ban and expiry off or 60s–366d.')
    return policy


def legacy(settings):
    policy={key:settings.get(old,DEFAULT[key]) for key,old in [('limit','warn_limit'),('action','warn_action'),('expiry_seconds','warn_expiry_seconds')]}
    try:
        policy['limit']=max(0,min(20,int(policy['limit'])))
        if policy['action'] not in ('mute','kick','ban'):
            policy['action']='mute'
        return validate(policy)
    except (TypeError,ValueError):
        raise PolicyError('Legacy warning policy is invalid; no policy imported.') from None


async def operate(store,group,*,actor=None,changes=None):
    if type(group) is not int or not -(2**63)<group<0:
        raise PolicyError('Warning policy requires a group identity.')
    if changes is not None:
        if not isinstance(changes,dict) or not changes or set(changes)-set(DEFAULT) or type(actor) is not int or not 0<actor<2**63:
            raise PolicyError('A personal administrator and valid policy fields are required.')
        validate({**DEFAULT,**changes})
    db=getattr(store,'_db',None)
    if db is None:
        current=legacy({key:store.get(group,key) for key in ('warn_limit','warn_action','warn_expiry_seconds') if store.get(group,key) is not None})
        if changes is not None:
            current=validate({**current,**changes})
            for key,old in [('limit','warn_limit'),('action','warn_action'),('expiry_seconds','warn_expiry_seconds')]:
                store.put(group,old,current[key])
            store.log(group,'warnpolicy',actor_id=actor,reason=f"{current['limit']}:{current['action']}")
        return current
    if not db.connected or getattr(db,'_pool',None) is None:
        raise PolicyError('Database warning policy unavailable. No policy change confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'warnpolicy:{group}'),timeout=5)
                raw=await conn.fetchval('SELECT policy FROM agent_warning_policies WHERE tenant=$1 AND group_id=$2',db.scope,group,timeout=5)
                if raw is None:
                    old=await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1',db.name_for('chats'),timeout=5)
                    old=json.loads(old) if isinstance(old,str) else old
                    current=legacy((old or {}).get(str(group),{}).get('settings',{}))
                    await conn.execute('INSERT INTO agent_warning_policies(tenant,group_id,policy) VALUES($1,$2,$3::jsonb)',db.scope,group,json.dumps(current),timeout=5)
                    await conn.execute('INSERT INTO agent_warning_policy_history(tenant,group_id,actor_id,policy) VALUES($1,$2,0,$3::jsonb)',db.scope,group,json.dumps(current),timeout=5)
                else:
                    current=validate(json.loads(raw) if isinstance(raw,str) else dict(raw))
                if changes is not None:
                    current=validate({**current,**changes})
                    await conn.execute('UPDATE agent_warning_policies SET policy=$3::jsonb WHERE tenant=$1 AND group_id=$2',db.scope,group,json.dumps(current),timeout=5)
                    await conn.execute('INSERT INTO agent_warning_policy_history(tenant,group_id,actor_id,policy) VALUES($1,$2,$3,$4::jsonb)',db.scope,group,actor,json.dumps(current),timeout=5)
        return current
    except PolicyError:
        raise
    except Exception:
        raise PolicyError('Warning policy read or commit unconfirmed. Re-read before retrying; no automatic retry.') from None


async def threshold(store,group):
    policy=await operate(store,group)
    return policy['limit'],policy['action']
