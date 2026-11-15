"""Durable automatic-restart admission, separate from worker startup failures."""
import json
import math

from ..modules.clone.lifecycle import backoff


class CloneRecovery:
    def __init__(self, database):
        self.database = database

    async def reserve(self, bot_id, maximum):
        db = self.database
        if not db.connected or db._pool is None:
            raise RuntimeError('Clone recovery authority unavailable')
        key = db.name_for(f'clone_recovery:{int(bot_id)}')
        async with db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
                raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key)
                raw = json.loads(raw) if isinstance(raw, str) else raw
                history = [] if raw is None else raw['attempts']
                if not isinstance(history, list) or len(history) > 10000 or any(type(t) not in (int, float) or not math.isfinite(t) for t in history):
                    raise RuntimeError('Invalid clone recovery history')
                now = float(await conn.fetchval('SELECT EXTRACT(EPOCH FROM clock_timestamp())'))
                history = [stamp for stamp in history if now - stamp < 3600]
                if len(history) >= maximum:
                    return 'exhausted'
                if history and now < history[-1] + backoff(len(history)):
                    return 'waiting'
                history.append(now)
                await conn.execute('''INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)
                    ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value''', key, json.dumps({'attempts': history}))
                return 'ready'
