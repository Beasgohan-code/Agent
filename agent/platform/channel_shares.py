"""Durable channel-invite Linkshare configuration, separate from legacy file links.

Configuration alone never creates invites or approves join requests. Telegram
identity/rights checks belong at every handler mutation and delivery boundary.
"""

SCHEMA = ('''CREATE TABLE IF NOT EXISTS agent_channel_shares (
    tenant TEXT NOT NULL,
    channel_id BIGINT NOT NULL CHECK (channel_id < 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    auto_approve BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by BIGINT NOT NULL CHECK (updated_by > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, channel_id))''',
    '''CREATE TABLE IF NOT EXISTS agent_channel_share_tokens (
    tenant TEXT NOT NULL, token_hash TEXT NOT NULL,
    channel_id BIGINT NOT NULL, request_mode BOOLEAN NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant,token_hash),
    FOREIGN KEY (tenant,channel_id) REFERENCES agent_channel_shares(tenant,channel_id)
    ON DELETE CASCADE)''',)

MAX_CHANNELS = 20


def personal_id(value):
    return type(value) is int and 0 < value < 2**63


def channel_id(value):
    if type(value) is not int or not -(2**63) < value < 0:
        raise ValueError('Use a valid negative channel ID.')


class ChannelShares:
    def __init__(self, db):
        self.db = db

    def pool(self):
        if self.db is None or not self.db.connected or self.db._pool is None:
            raise RuntimeError('Channel-share storage unavailable.')
        return self.db._pool

    async def get(self, channel):
        channel_id(channel)
        async with self.pool().acquire(timeout=5) as conn:
            row = await conn.fetchrow('SELECT channel_id,enabled,auto_approve,updated_by FROM agent_channel_shares WHERE tenant=$1 AND channel_id=$2',
                                      self.db.scope, channel, timeout=5)
        return dict(row) if row is not None else None

    async def list(self):
        async with self.pool().acquire(timeout=5) as conn:
            rows = await conn.fetch('SELECT channel_id,enabled,auto_approve,updated_by FROM agent_channel_shares WHERE tenant=$1 ORDER BY channel_id LIMIT $2',
                                    self.db.scope, MAX_CHANNELS, timeout=5)
        return [dict(row) for row in rows]

    async def configure(self, channel, *, actor, enabled=None, auto_approve=None):
        channel_id(channel)
        if not personal_id(actor):
            raise ValueError('Personal administrator identity required.')
        if any(value is not None and type(value) is not bool for value in (enabled, auto_approve)):
            raise ValueError('Channel settings must be explicit booleans.')
        async with self.pool().acquire(timeout=5) as conn:
            async with conn.transaction():
                # Same tenant lock for quota admission and all field patches;
                # independent worker snapshots never overwrite another field.
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                   self.db.scope + ':channel-shares', timeout=5)
                old = await conn.fetchrow('SELECT enabled,auto_approve FROM agent_channel_shares WHERE tenant=$1 AND channel_id=$2',
                                          self.db.scope, channel, timeout=5)
                if old is None:
                    count = await conn.fetchval('SELECT count(*) FROM agent_channel_shares WHERE tenant=$1', self.db.scope, timeout=5)
                    if count >= MAX_CHANNELS:
                        raise ValueError('Channel-share limit reached (20 channels).')
                active = enabled if enabled is not None else (old['enabled'] if old else True)
                automatic = auto_approve if auto_approve is not None else (old['auto_approve'] if old else False)
                row = await conn.fetchrow('''INSERT INTO agent_channel_shares
                    (tenant,channel_id,enabled,auto_approve,updated_by) VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT(tenant,channel_id) DO UPDATE SET enabled=EXCLUDED.enabled,
                    auto_approve=EXCLUDED.auto_approve,updated_by=EXCLUDED.updated_by,updated_at=now()
                    RETURNING channel_id,enabled,auto_approve,updated_by''',
                    self.db.scope, channel, active, automatic, actor, timeout=5)
        return dict(row)


    async def issue(self, channel):
        """Create two opaque 30-day bot links atomically; raw tokens never stored."""
        import hashlib
        import secrets
        channel_id(channel)
        tokens = {mode: secrets.token_urlsafe(18) for mode in ('normal', 'request')}
        async with self.pool().acquire(timeout=5) as conn:
            async with conn.transaction():
                policy = await conn.fetchrow('SELECT enabled FROM agent_channel_shares WHERE tenant=$1 AND channel_id=$2 FOR UPDATE',
                                             self.db.scope, channel, timeout=5)
                if policy is None or policy['enabled'] is not True:
                    raise ValueError('Managed channel unavailable')
                await conn.execute('DELETE FROM agent_channel_share_tokens WHERE tenant=$1 AND expires_at<=now()', self.db.scope, timeout=5)
                count = await conn.fetchval('SELECT count(*) FROM agent_channel_share_tokens WHERE tenant=$1 AND channel_id=$2', self.db.scope, channel, timeout=5)
                if count >= 200:
                    raise ValueError('Channel bot-link quota reached')
                for mode, token in tokens.items():
                    await conn.execute("""INSERT INTO agent_channel_share_tokens
                        (tenant,token_hash,channel_id,request_mode,expires_at)
                        VALUES($1,$2,$3,$4,now()+interval '30 days')""",
                        self.db.scope, hashlib.sha256(token.encode()).hexdigest(), channel, mode == 'request', timeout=5)
        return tokens

    async def resolve(self, token):
        import hashlib
        import re
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{24}', token):
            return None
        async with self.pool().acquire(timeout=5) as conn:
            row = await conn.fetchrow("""SELECT t.channel_id,t.request_mode
                FROM agent_channel_share_tokens t JOIN agent_channel_shares c
                ON c.tenant=t.tenant AND c.channel_id=t.channel_id
                WHERE t.tenant=$1 AND t.token_hash=$2 AND t.expires_at>now() AND c.enabled=TRUE""",
                self.db.scope, hashlib.sha256(token.encode()).hexdigest(), timeout=5)
        return dict(row) if row is not None else None
