"""Awaited tenant/group Post Maker templates; no configured-DB disk fallback."""
SCHEMA = ('''CREATE TABLE IF NOT EXISTS agent_post_templates (
    tenant TEXT NOT NULL, group_id BIGINT NOT NULL,
    template TEXT NOT NULL CHECK (char_length(template) <= 600),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant,group_id))''',)


class PostTemplates:
    def __init__(self, db):
        self.db = db

    def pool(self):
        if not self.db.connected or self.db._pool is None:
            raise RuntimeError('Database template settings unavailable')
        return self.db._pool

    async def get(self, group_id, legacy):
        async with self.pool().acquire(timeout=5) as conn:
            value = await conn.fetchval('SELECT template FROM agent_post_templates WHERE tenant=$1 AND group_id=$2',
                                        self.db.scope, group_id, timeout=5)
        # Existing document layout is retained until first explicit template save.
        return legacy if value is None else value

    async def set(self, group_id, template):
        if not isinstance(template, str) or len(template) > 600:
            raise ValueError('Template exceeds limit')
        async with self.pool().acquire(timeout=5) as conn:
            await conn.execute('''INSERT INTO agent_post_templates (tenant,group_id,template)
                VALUES ($1,$2,$3) ON CONFLICT (tenant,group_id) DO UPDATE
                SET template=EXCLUDED.template,updated_at=now()''', self.db.scope, group_id, template, timeout=5)
