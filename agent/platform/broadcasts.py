"""Scoped broadcast admission and outcomes; never replay admitted effects."""
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_broadcasts (
        tenant TEXT NOT NULL, request_id BIGINT NOT NULL, owner_id BIGINT NOT NULL,
        source_id BIGINT NOT NULL, mode TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(tenant,request_id))""",
    """CREATE TABLE IF NOT EXISTS agent_broadcast_items (
        tenant TEXT NOT NULL, request_id BIGINT NOT NULL, recipient BIGINT NOT NULL,
        outcome TEXT NOT NULL DEFAULT 'admitted', destination_id BIGINT,
        PRIMARY KEY(tenant,request_id,recipient),
        FOREIGN KEY(tenant,request_id) REFERENCES agent_broadcasts(tenant,request_id))""",
)


def database(ctx):
    db = getattr(ctx, 'db', None)
    if db is None or not db.connected or getattr(db, '_pool', None) is None:
        raise ValueError('PostgreSQL is required. No broadcast admitted.')
    return db


async def admit(ctx, request_id, owner, source, mode, recipients):
    db = database(ctx)
    if ctx.settings.owner_id != owner or type(request_id) is not int or request_id <= 0 or type(source) is not int or source <= 0 or mode not in ('-user', '-chat'):
        raise ValueError('Broadcast admission identity/configuration invalid.')
    if not 1 <= len(recipients) <= 50 or len(set(recipients)) != len(recipients) or any(type(i) is not int or not -(2**63) < i < 2**63 or (i <= 0 if mode == '-user' else i >= 0) for i in recipients):
        raise ValueError('Broadcast requires 1–50 unique matching recipients.')
    async with db._pool.acquire(timeout=5) as conn:
        async with conn.transaction():
            inserted = await conn.fetchval('INSERT INTO agent_broadcasts(tenant,request_id,owner_id,source_id,mode) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING RETURNING request_id', db.scope, request_id, owner, source, mode)
            if inserted is None:
                return False
            await conn.executemany('INSERT INTO agent_broadcast_items(tenant,request_id,recipient) VALUES($1,$2,$3)', [(db.scope, request_id, uid) for uid in recipients])
    return True


async def outcome(ctx, request_id, recipient, state, destination=None):
    if state not in ('sending', 'forwarded', 'unconfirmed'):
        raise ValueError('Invalid broadcast outcome')
    db = database(ctx)
    async with db._pool.acquire(timeout=5) as conn:
        await conn.execute('UPDATE agent_broadcast_items SET outcome=$4,destination_id=$5 WHERE tenant=$1 AND request_id=$2 AND recipient=$3', db.scope, request_id, recipient, state, destination)
