"""Awaited warning history, isolated from stale whole-chat document writers."""
import copy
import json

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_member_warnings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL CHECK(group_id<0),
    user_id BIGINT NOT NULL CHECK(user_id>0), payload JSONB NOT NULL,
    PRIMARY KEY(tenant,group_id,user_id))""",
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
