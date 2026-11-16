"""Awaited warning history, isolated from stale whole-chat document writers."""
import copy
import json
import time

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_member_warnings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    user_id BIGINT NOT NULL CHECK(user_id>0), payload JSONB NOT NULL,
    PRIMARY KEY(tenant,group_id,user_id))""",
    """CREATE TABLE IF NOT EXISTS agent_warning_group_resets (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    request_id BIGINT NOT NULL CHECK(request_id>0), actor_id BIGINT NOT NULL CHECK(actor_id>0),
    cleared INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant,group_id,request_id))""",
)


class WarningStoreError(RuntimeError):
    """Warning state is unavailable or its mutation was not confirmed."""


async def operate(store, chat_id, user_id, operation, **fields):
    if operation not in {'add_warning', 'clear_warning', 'clear_all_warnings', 'warnings_of'}:
        raise WarningStoreError('Invalid warning operation.')
    if (type(chat_id) is not int or not -(2**63) < chat_id < 0
            or type(user_id) is not int or not 0 < user_id < 2**63):
        raise WarningStoreError('A group and personal member identity are required.')
    if operation == 'add_warning' and (
            type(fields.get('moderator_id')) is not int
            or not 0 <= fields['moderator_id'] < 2**63
            or not isinstance(fields.get('reason'), str)):
        raise WarningStoreError('Invalid warning actor or reason.')
    db = store._db
    if db is None:
        return getattr(store, operation)(chat_id, user_id, **fields)
    if not db.connected or db._pool is None:
        raise WarningStoreError('PostgreSQL warning state unavailable. No changes confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                   db.name_for(f'warnings-group:{chat_id}'), timeout=5)
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                   db.name_for(f'warnings:{chat_id}:{user_id}'), timeout=5)
                raw = await conn.fetchval('''SELECT payload FROM agent_member_warnings
                    WHERE tenant=$1 AND group_id=$2 AND user_id=$3 FOR UPDATE''',
                    db.scope, chat_id, user_id, timeout=5)
                if raw is None:
                    legacy = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1',
                                                 db.name_for('chats'), timeout=5)
                    legacy = json.loads(legacy) if isinstance(legacy, str) else legacy
                    rows = (legacy or {}).get(str(chat_id), {}).get('members', {}).get(str(user_id), {}).get('warnings', [])
                else:
                    rows = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise WarningStoreError('Persisted warning history invalid.')
                # Reuse the bounded standalone transformation, never its file I/O.
                from .chats import ChatStore
                work = ChatStore.__new__(ChatStore)
                work._db = None
                work._chats = {}
                work._max_warnings = store._max_warnings
                work._save = lambda: None
                work._member(chat_id, user_id)['warnings'] = copy.deepcopy(rows)
                result = getattr(work, operation)(chat_id, user_id, **fields)
                # Persist even a first read/empty clear: legacy import is one-time,
                # so later stale document flushes cannot resurrect cleared history.
                await conn.execute('''INSERT INTO agent_member_warnings(tenant,group_id,user_id,payload)
                    VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(tenant,group_id,user_id)
                    DO UPDATE SET payload=EXCLUDED.payload''', db.scope, chat_id, user_id,
                    json.dumps(work._member(chat_id, user_id)['warnings']), timeout=5)
        return copy.deepcopy(result)
    except WarningStoreError:
        raise
    except Exception:
        raise WarningStoreError('Warning state unavailable or result unconfirmed. Refresh before retrying.') from None


async def reset_group(store, chat_id, *, actor, request_id):
    """Clear flags, not history, under the same group lock as member writers."""
    if (type(chat_id) is not int or not -(2**63) < chat_id < 0
            or any(type(v) is not int or not 0 < v < 2**63 for v in (actor, request_id))):
        raise WarningStoreError('Valid group, personal administrator and request identities required.')
    db = store._db
    if db is None or not db.connected or getattr(db, '_pool', None) is None:
        raise WarningStoreError('PostgreSQL is required for a group-wide warning reset. No changes confirmed.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                   db.name_for(f'warnings-group:{chat_id}'), timeout=5)
                admitted = await conn.fetchval(
                    'INSERT INTO agent_warning_group_resets(tenant,group_id,request_id,actor_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING request_id',
                    db.scope, chat_id, request_id, actor, timeout=5)
                if admitted is None:
                    raise WarningStoreError('This warning reset was already committed. No new warnings cleared.')
                legacy = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1',db.name_for('chats'),timeout=5)
                legacy = json.loads(legacy) if isinstance(legacy,str) else legacy
                members = (legacy or {}).get(str(chat_id),{}).get('members',{})
                if not isinstance(members,dict) or len(members)>10000:
                    raise WarningStoreError('Legacy warning member index invalid or exceeds 10,000-member reset bound.')
                merged = {}
                for key, member in members.items():
                    if isinstance(key,str) and key.isascii() and key.isdigit() and len(key)<=19 and 0<int(key)<2**63:
                        merged[int(key)] = member.get('warnings',[]) if isinstance(member,dict) else None
                rows = await conn.fetch('SELECT user_id,payload FROM agent_member_warnings WHERE tenant=$1 AND group_id=$2 LIMIT 10001',db.scope,chat_id,timeout=5)
                if len(rows)>10000:
                    raise WarningStoreError('Group warning index exceeds 10,000-member reset bound.')
                for row in rows:
                    value = row['payload']
                    merged[row['user_id']] = json.loads(value) if isinstance(value,str) else value
                if len(merged)>10000:
                    raise WarningStoreError('Combined warning index exceeds reset bound.')
                cleared, updates, now = 0, [], time.time()
                for uid, history in merged.items():
                    if not isinstance(history,list) or any(not isinstance(w,dict) for w in history):
                        raise WarningStoreError('Warning history invalid. Reset rolled back.')
                    for warning in history:
                        if warning.get('active'):
                            cleared += 1
                            warning.update(active=False,cleared_at=now)
                    updates.append((db.scope,chat_id,uid,json.dumps(history)))
                # Persist even empty histories: stale legacy writers cannot resurrect them.
                if updates:
                    await conn.executemany('INSERT INTO agent_member_warnings(tenant,group_id,user_id,payload) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(tenant,group_id,user_id) DO UPDATE SET payload=EXCLUDED.payload',updates,timeout=20)
                await conn.execute('UPDATE agent_warning_group_resets SET cleared=$4 WHERE tenant=$1 AND group_id=$2 AND request_id=$3',db.scope,chat_id,request_id,cleared,timeout=5)
        return cleared
    except WarningStoreError:
        raise
    except Exception:
        raise WarningStoreError('Group reset unconfirmed. Inspect /warns before issuing another request.') from None
