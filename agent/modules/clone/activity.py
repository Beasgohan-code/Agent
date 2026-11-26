"""Read-only, redacted lifecycle admission history for a current saved owner.

Receipts are not completion events. No credential snapshots or raw values leave
this reader. Registry lock order matches lifecycle/configuration authorities.
"""
import json
import math

from .control_actions import ControlConflict

PAGE_SIZE = 6
ACTIONS = frozenset(('start', 'stop', 'restart', 'reconcile', 'delete'))


async def read_activity(store, bot_id, actor_id, page=0):
    if (type(bot_id) is not int or bot_id <= 0 or type(actor_id) is not int or actor_id <= 0
            or type(page) is not int or not 0 <= page <= 9999):
        raise ControlConflict('Invalid activity request.')
    db = store._db
    if db is None or not db.connected or db._pool is None:
        raise ControlConflict('Durable activity requires available storage.')
    try:
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                key = db.name_for('clones')
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
                raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key, timeout=5)
                raw = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(raw, list):
                    raise ControlConflict('Saved clone authority unavailable.')
                items = store._decode(raw)
                if len(items) != len(raw) or bot_id not in items or items[bot_id].owner_id != actor_id:
                    raise ControlConflict('Clone activity access refused. Refresh My Bots.')
                prefix = db.name_for(f'clone_control:{bot_id}:')
                # Exact prefix, not LIKE: scope names may contain wildcard characters.
                records = await conn.fetch('''SELECT value FROM agent_documents
                    WHERE left(name,length($1::text))=$1
                    ORDER BY updated_at DESC,name DESC LIMIT $2 OFFSET $3''',
                    prefix, PAGE_SIZE + 1, page * PAGE_SIZE, timeout=5)
                if page and not records:
                    raise ControlConflict('That activity page changed. Refresh the dashboard.')
                result = []
                for row in records[:PAGE_SIZE]:
                    value = row['value']
                    try:
                        value = json.loads(value) if isinstance(value, str) else value
                        if not isinstance(value, dict) or value.get('bot_id') != bot_id or value.get('status') != 'admitted':
                            raise ValueError
                        action = value.get('action')
                        revision, generation, at = value['revision'], value['assigned_generation'], value['at']
                        if (type(action) is not str or action not in ACTIONS or type(revision) is not int or not 0 < revision < 10**12
                                or type(generation) is not int or not 0 <= generation < 10**12
                                or type(at) not in (int, float) or not math.isfinite(at) or not 0 < at < 253402300800):
                            raise ValueError
                        result.append(dict(action=action, revision=revision, generation=generation, at=at))
                    except (ValueError, KeyError, TypeError):
                        result.append(None)  # Preserve pagination but never echo malformed values.
                return result, len(records) > PAGE_SIZE
    except ControlConflict:
        raise
    except Exception:
        raise ControlConflict('Activity could not be read safely. Refresh after checking controller availability.') from None
