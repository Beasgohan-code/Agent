"""Canonical member notes with serialized writes and content-free change metadata."""
import json

SCHEMA=(
    """CREATE TABLE IF NOT EXISTS agent_member_notes (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0), user_id BIGINT NOT NULL CHECK(user_id>0),
    body TEXT NOT NULL CHECK(length(body)<=2000), version BIGINT NOT NULL DEFAULT 0,
    updated_by BIGINT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant,group_id,user_id))""",
    """CREATE TABLE IF NOT EXISTS agent_member_note_changes (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL, user_id BIGINT NOT NULL, version BIGINT NOT NULL,
    actor_id BIGINT NOT NULL, characters INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,group_id,user_id,version))""",
)


class NoteError(RuntimeError):
    """Safe note read/commit failure."""


async def operate(store,group,user,*,body=None,actor=None):
    if (type(group) is not int or not -(2**63)<group<0 or type(user) is not int or not 0<user<2**63):
        raise NoteError('A valid group and personal member identity are required.')
    if body is not None and (not isinstance(body,str) or not 1<=len(body)<=2000 or type(actor) is not int or not 0<actor<2**63):
        raise NoteError('Note must be 1–2000 characters with a personal administrator identity.')
    db=getattr(store,'_db',None)
    if db is None:
        if body is not None:
            store.set_note(group,user,body)
        return {'body':store.note_of(group,user),'version':0}
    if not db.connected or getattr(db,'_pool',None) is None:
        raise NoteError('PostgreSQL notes unavailable. No note change confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',db.name_for(f'note:{group}:{user}'),timeout=5)
                row=await conn.fetchrow('SELECT body,version FROM agent_member_notes WHERE tenant=$1 AND group_id=$2 AND user_id=$3',db.scope,group,user,timeout=5)
                if row is None:
                    raw=await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1',db.name_for('chats'),timeout=5)
                    raw=json.loads(raw) if isinstance(raw,str) else raw
                    old=(raw or {}).get(str(group),{}).get('members',{}).get(str(user),{}).get('note','')
                    if not isinstance(old,str) or len(old)>2000:
                        raise NoteError('Stored legacy note invalid; no import confirmed.')
                    await conn.execute('INSERT INTO agent_member_notes(tenant,group_id,user_id,body,updated_by) VALUES($1,$2,$3,$4,0)',db.scope,group,user,old,timeout=5)
                    row={'body':old,'version':0}
                result=dict(row)
                if body is not None:
                    result={'body':body,'version':row['version']+1}
                    await conn.execute('UPDATE agent_member_notes SET body=$4,version=$5,updated_by=$6,updated_at=now() WHERE tenant=$1 AND group_id=$2 AND user_id=$3',db.scope,group,user,body,result['version'],actor,timeout=5)
                    await conn.execute('INSERT INTO agent_member_note_changes(tenant,group_id,user_id,version,actor_id,characters) VALUES($1,$2,$3,$4,$5,$6)',db.scope,group,user,result['version'],actor,len(body),timeout=5)
        return result
    except NoteError:
        raise
    except Exception:
        raise NoteError('Note read or commit unconfirmed. Re-read warnings before retrying; no automatic retry.') from None
