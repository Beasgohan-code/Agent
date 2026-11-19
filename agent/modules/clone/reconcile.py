"""Revision-assigned worker reconciliation, not an execution sandbox.

A short-lived, unique attempt lease excludes competing reconcilers. No database
transaction spans worker I/O. Commit checks both leases using database time and
locks them against replacement, then CASes the exact desired/pending revision.
Application callbacks must replace/stop partial workers on failure. A lost ack
is recovered by reapplying, never by inferring success from a durable receipt.
"""
import asyncio
import json
import uuid
from dataclasses import replace

from .revisions import RevisionConflict
from .store import Clone


class ReconciliationError(RuntimeError):
    pass


class CloneReconciler:
    def __init__(self, repository, *, ttl=60):
        self.repo = repository
        self.ttl = ttl

    def claim_key(self, bot_id):
        return self.repo.db.name_for(f'clone_reconcile:{bot_id}')

    @staticmethod
    def worker_key(bot_id):
        # This is the existing AgentBot clone tenant's InstanceLease key.
        return f'clone:{bot_id}:agent'

    async def _claim(self, bot_id, attempt):
        self.repo._available()
        async with self.repo.db._pool.acquire(timeout=5) as conn:
            result = await conn.fetchval('''INSERT INTO agent_lease(name,holder,expires_at)
                VALUES($1,$2,EXTRACT(EPOCH FROM clock_timestamp())+$3)
                ON CONFLICT(name) DO UPDATE SET holder=$2,expires_at=EXCLUDED.expires_at
                WHERE agent_lease.expires_at <= EXTRACT(EPOCH FROM clock_timestamp())
                RETURNING holder''', self.claim_key(bot_id), attempt, self.ttl, timeout=5)
            if result != attempt:
                raise ReconciliationError('Reconciliation already owned')

    async def acknowledge(self, bot_id, *, revision, attempt, worker_owner, generation):
        """Internal commit authority: both holders and expiry fenced in SQL."""
        if type(generation) is not int or generation < 0:
            raise RevisionConflict('Worker lifecycle assignment required')
        repo = self.repo
        async with repo._locked(bot_id, with_connection=True, registry_lock=True) as (state, _, conn):
            await self._registry_owner(conn, bot_id, state, generation=generation)
            for key, holder in ((self.claim_key(bot_id), attempt), (self.worker_key(bot_id), worker_owner)):
                valid = await conn.fetchval('''SELECT holder=$2 AND expires_at > EXTRACT(EPOCH FROM clock_timestamp())
                    FROM agent_lease WHERE name=$1 FOR UPDATE''', key, holder, timeout=5)
                if valid is not True:
                    raise RevisionConflict('Worker ownership expired or replaced')
            if (type(revision) is not int or revision <= 0 or state['desired_revision'] != revision
                    or state['pending_revision'] != revision):
                raise RevisionConflict('Stale reconciliation acknowledgement')
            now = float(await conn.fetchval('SELECT EXTRACT(EPOCH FROM clock_timestamp())'))
            state.update(previous_applied_snapshot=state['applied_snapshot'], applied_snapshot=state['desired_snapshot'],
                         applied_revision=revision, pending_revision=None, configuration_status='applied',
                         last_applied_at=now, updated_at=now, last_error_code=None)
            return repo._metadata(state)

    async def _registry_owner(self, conn, bot_id, state, *, generation=None):
        raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE',
                                  self.repo.db.name_for('clones'), timeout=5)
        raw = json.loads(raw) if isinstance(raw, str) else raw
        snapshot = json.loads(self.repo.box.decrypt(state['desired_snapshot']))
        matches = [row for row in raw if row.get('bot_id') == bot_id] if isinstance(raw, list) else []
        if len(matches) != 1 or matches[0].get('owner_id') != snapshot['owner_id']:
            raise RevisionConflict('Clone registry ownership changed')
        row = matches[0]
        epoch = row.get('lifecycle_generation', 0)
        if (type(epoch) is not int or epoch < 0 or row.get('disabled', False) is not False
                or (generation is not None and (type(generation) is not int or epoch != generation))):
            raise RevisionConflict('Clone lifecycle changed')
        token = self.repo.box.decrypt(row.get('token_enc') or row.get('token') or '')
        if token != snapshot['token']:
            raise RevisionConflict('Clone credentials changed')
        return epoch

    async def _configuration(self, bot_id, revision, generation=None):
        async with self.repo._locked(bot_id, with_connection=True, registry_lock=True) as (state, _, conn):
            epoch = await self._registry_owner(conn, bot_id, state, generation=generation)
        if type(revision) is not int or revision <= 0 or state['desired_revision'] != revision:
            raise RevisionConflict('Stale reconciliation assignment')
        pending = state['pending_revision'] == revision
        if not pending and state['applied_revision'] != revision:
            raise RevisionConflict('Revision is not available for recovery')
        snapshot = state['desired_snapshot'] if pending else state['applied_snapshot']
        fields = json.loads(self.repo.box.decrypt(snapshot))
        fields['selected_plugins'] = tuple(fields.get('selected_plugins', ()))
        config = replace(Clone(**fields), lifecycle_generation=epoch, disabled=False)
        if config.bot_id != bot_id:
            raise RevisionConflict('Configuration identity mismatch')
        self.repo.validate(config)
        return config, pending, state

    async def run(self, bot_id, *, revision, apply, generation=None):
        attempt = uuid.uuid4().hex
        claimed = False
        try:
            if not callable(apply):
                raise ReconciliationError('Configuration application unavailable')
            await self._claim(bot_id, attempt)
            claimed = True
            config, pending, state = await self._configuration(bot_id, revision, generation)
            worker = await apply(config)
            if not getattr(worker, 'owner', None):
                raise ReconciliationError('Worker Database ownership unavailable')
            if pending:
                return await self.acknowledge(bot_id, revision=revision, attempt=attempt, worker_owner=worker.owner, generation=config.lifecycle_generation)
            # Restart of an acknowledged revision must still verify ownership
            # and reject a desired change that arrived while applying it.
            async with self.repo._locked(bot_id, with_connection=True, registry_lock=True) as (current, _, conn):
                await self._registry_owner(conn, bot_id, current, generation=config.lifecycle_generation)
                for key, owner in ((self.claim_key(bot_id), attempt), (self.worker_key(bot_id), worker.owner)):
                    valid = await conn.fetchval('''SELECT holder=$2 AND expires_at>EXTRACT(EPOCH FROM clock_timestamp())
                        FROM agent_lease WHERE name=$1 FOR UPDATE''', key, owner)
                    if valid is not True:
                        raise RevisionConflict('Worker ownership expired or replaced')
                if current['desired_revision'] != revision or current['applied_revision'] != revision:
                    raise RevisionConflict('Stale recovery assignment')
                return self.repo._metadata(current)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ReconciliationError('Clone reconciliation not confirmed; revision remains authoritative') from None
        finally:
            if claimed:
                try:
                    async with self.repo.db._pool.acquire(timeout=5) as conn:
                        await conn.execute('DELETE FROM agent_lease WHERE name=$1 AND holder=$2', self.claim_key(bot_id), attempt, timeout=5)
                except Exception:
                    pass  # Expiry permits retry; never log a credential-bearing driver error.
