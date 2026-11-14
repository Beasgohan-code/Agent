"""Secret-minimizing, tenant-scoped incident aggregation; no raw exception text."""
import hashlib
import json
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path

SCHEMA = ('''CREATE TABLE IF NOT EXISTS agent_error_incidents (
    tenant TEXT NOT NULL, fingerprint TEXT NOT NULL, incident_id TEXT NOT NULL,
    error_type TEXT NOT NULL, handler TEXT NOT NULL, frames JSONB NOT NULL,
    occurrences BIGINT NOT NULL DEFAULT 1,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant,fingerprint), UNIQUE(tenant,incident_id))''',)


def label(value):
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', value)[:80]


def describe(error, handler):
    frames, trace = [], error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        frames.append(f'{label(Path(code.co_filename).name)}:{trace.tb_lineno}:{label(code.co_name)}')
        trace = trace.tb_next
    # Never stringify error, inspect locals, or collect the incoming update.
    fields = {'error_type': label(type(error).__name__), 'handler': label(type(handler).__name__), 'frames': frames[-8:]}
    fields['fingerprint'] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:32]
    return fields


class ErrorIncidents:
    def __init__(self, db):
        self.db = db
        self._recent = OrderedDict()

    async def capture(self, error, handler):
        fields = describe(error, handler)
        result = {**fields, 'incident_id': uuid.uuid4().hex[:16], 'occurrences': 1, 'saved': False}
        db = self.db
        if db is not None and db.connected and db._pool is not None:
            try:
                async with db._pool.acquire(timeout=5) as conn:
                    async with conn.transaction():
                        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                           'agent:incidents:' + db.scope, timeout=5)
                        row = await conn.fetchrow('''INSERT INTO agent_error_incidents
                            (tenant,fingerprint,incident_id,error_type,handler,frames)
                            VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                            ON CONFLICT (tenant,fingerprint) DO UPDATE
                            SET occurrences=agent_error_incidents.occurrences+1,last_seen=now()
                            RETURNING incident_id,occurrences''', db.scope, fields['fingerprint'], result['incident_id'],
                            fields['error_type'], fields['handler'], json.dumps(fields['frames']), timeout=5)
                        await conn.execute('''DELETE FROM agent_error_incidents WHERE tenant=$1
                            AND fingerprint NOT IN (SELECT fingerprint FROM agent_error_incidents
                            WHERE tenant=$1 ORDER BY last_seen DESC,fingerprint LIMIT 100)''', db.scope, timeout=5)
                    result.update(incident_id=row['incident_id'], occurrences=row['occurrences'], saved=True)
            except Exception:
                pass  # error reporting cannot kill the handler error boundary
        now = time.monotonic()
        previous = self._recent.get(fields['fingerprint'])
        result['notify'] = previous is None or now - previous >= 60
        if result['notify']:
            self._recent[fields['fingerprint']] = now
            self._recent.move_to_end(fields['fingerprint'])
        while len(self._recent) > 200:
            self._recent.popitem(last=False)
        return result

    async def recent(self):
        db = self.db
        if db is None or not db.connected or db._pool is None:
            raise RuntimeError('PostgreSQL incident history is unavailable.')
        async with db._pool.acquire(timeout=5) as conn:
            return await conn.fetch('''SELECT incident_id,error_type,handler,occurrences,last_seen
                FROM agent_error_incidents WHERE tenant=$1 ORDER BY last_seen DESC LIMIT 10''', db.scope, timeout=5)
