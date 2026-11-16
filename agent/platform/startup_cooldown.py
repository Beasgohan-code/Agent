"""Awaited, tenant-scoped Telegram startup cooldown; contains no credentials."""


class StartupCooldown:
    def __init__(self, database):
        self.database = database

    def _pool(self):
        db = self.database
        if not db.connected or db._pool is None:
            raise RuntimeError('Startup cooldown storage is unavailable; refusing early retry.')
        return db._pool

    async def remaining(self):
        async with self._pool().acquire() as conn:
            seconds = await conn.fetchval(
                """SELECT GREATEST(0, (value->>'retry_at')::double precision
                   - EXTRACT(EPOCH FROM clock_timestamp())) FROM agent_documents WHERE name=$1""",
                self.database.name_for('telegram_startup_cooldown'))
        return float(seconds or 0)

    async def extend(self, seconds):
        if type(seconds) is not int or seconds <= 0:
            raise ValueError('Cooldown seconds must be a positive integer.')
        async with self._pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_documents(name,value)
                   VALUES($1,jsonb_build_object('retry_at',EXTRACT(EPOCH FROM clock_timestamp())+$2::double precision))
                   ON CONFLICT(name) DO UPDATE SET value=jsonb_build_object('retry_at',
                   GREATEST((agent_documents.value->>'retry_at')::double precision,
                            (EXCLUDED.value->>'retry_at')::double precision))""",
                self.database.name_for('telegram_startup_cooldown'), seconds)
