"""Confirmed group greetings with atomic text-preserving toggles."""
SCHEMA = ('''CREATE TABLE IF NOT EXISTS agent_greetings (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('welcome','goodbye')),
    text TEXT NOT NULL CHECK (char_length(text) <= 1500),
    enabled BOOLEAN NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant,group_id,kind))''',)


class Greetings:
    def __init__(self, db):
        self.db = db

    def pool(self, kind):
        if kind not in ('welcome', 'goodbye'):
            raise ValueError('Unknown greeting kind')
        if not self.db.connected or self.db._pool is None:
            raise RuntimeError('PostgreSQL greetings unavailable')
        return self.db._pool

    async def get(self, group_id, kind, legacy):
        async with self.pool(kind).acquire(timeout=5) as conn:
            row = await conn.fetchrow('SELECT text,enabled FROM agent_greetings WHERE tenant=$1 AND group_id=$2 AND kind=$3',
                                       self.db.scope, group_id, kind, timeout=5)
        return dict(row) if row is not None else dict(legacy)

    async def set(self, group_id, kind, text):
        if not isinstance(text, str) or len(text) > 1500:
            raise ValueError('Greeting text exceeds limit')
        async with self.pool(kind).acquire(timeout=5) as conn:
            await conn.execute('''INSERT INTO agent_greetings (tenant,group_id,kind,text,enabled)
                VALUES ($1,$2,$3,$4,TRUE) ON CONFLICT (tenant,group_id,kind)
                DO UPDATE SET text=EXCLUDED.text,enabled=TRUE,updated_at=now()''',
                self.db.scope, group_id, kind, text, timeout=5)

    async def toggle(self, group_id, kind, enabled, legacy):
        if not isinstance(enabled, bool):
            raise ValueError('Greeting state must be boolean')
        async with self.pool(kind).acquire(timeout=5) as conn:
            row = await conn.fetchrow('''INSERT INTO agent_greetings (tenant,group_id,kind,text,enabled)
                VALUES ($1,$2,$3,$4,$5) ON CONFLICT (tenant,group_id,kind)
                DO UPDATE SET enabled=EXCLUDED.enabled,updated_at=now() RETURNING text,enabled''',
                self.db.scope, group_id, kind, legacy['text'], enabled, timeout=5)
        return dict(row)
