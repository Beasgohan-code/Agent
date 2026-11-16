"""Internal PostgreSQL revision repository, not a worker/entitlement authority.

Snapshots are encrypted as a whole. Canonical writes live in configuration.py;
worker application and lease-fenced acknowledgement live in reconcile.py.
The low-level propose primitive is retained for storage compatibility tests and
must not replace the canonical registry transaction in runtime call sites.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import copy
import json
import re

from .store import Clone


class RevisionConflict(RuntimeError):
    """The request is stale or reuses an id for a different configuration."""


METADATA = ('desired_revision', 'applied_revision', 'pending_revision',
            'last_failed_revision', 'configuration_status', 'updated_at',
            'last_applied_at', 'last_error_code')


def initial():
    # Zero does not assert that an existing legacy worker has applied anything.
    return dict(desired_revision=0, applied_revision=0, pending_revision=None,
                last_failed_revision=None, configuration_status='untracked',
                updated_at=None, last_applied_at=None, last_error_code=None,
                desired_snapshot=None, applied_snapshot=None, previous_applied_snapshot=None,
                request_id=None)


class CloneConfigurationRevisions:
    def __init__(self, database, *, box, validate):
        self.db, self.box, self.validate = database, box, validate
        if not callable(validate):
            raise ValueError('A trusted configuration validator is required')

    def key(self, bot_id):
        if type(bot_id) is not int or bot_id <= 0:
            raise ValueError('Invalid clone identity')
        return self.db.name_for(f'clone_configuration:{bot_id}')

    def _available(self):
        if not self.db.connected or self.db._pool is None or not self.box.enabled:
            raise RuntimeError('Encrypted PostgreSQL revision storage unavailable')

    @staticmethod
    def _decode(raw):
        if raw is None:
            return initial()
        raw = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(raw, dict) or set(raw) != set(initial()):
            raise RuntimeError('Invalid revision state')
        desired, applied = raw['desired_revision'], raw['applied_revision']
        if (type(desired) is not int or type(applied) is not int or not 0 <= applied <= desired
                or raw['configuration_status'] not in ('untracked', 'pending', 'applied', 'failed')):
            raise RuntimeError('Invalid revision state')
        for field in ('pending_revision', 'last_failed_revision'):
            if raw[field] is not None and (type(raw[field]) is not int or not 0 < raw[field] <= desired):
                raise RuntimeError('Invalid revision state')
        return raw

    @staticmethod
    def _metadata(state):
        return {field: state[field] for field in METADATA}

    @asynccontextmanager
    async def _locked(self, bot_id, *, with_connection=False, registry_lock=False):
        self._available()
        key = self.key(bot_id)
        async with self.db._pool.acquire(timeout=5) as conn:
            async with conn.transaction():
                if registry_lock:
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                       self.db.name_for('clones'), timeout=5)
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
                raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key)
                state = self._decode(raw)
                previous = copy.deepcopy(state)
                now = float(await conn.fetchval('SELECT EXTRACT(EPOCH FROM clock_timestamp())'))
                yield (state, now, conn) if with_connection else (state, now)
                if state != previous:
                    await conn.execute('''INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)
                        ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value,updated_at=now()''',
                                       key, json.dumps(state))

    async def read(self, bot_id):
        self._available()
        async with self.db._pool.acquire(timeout=5) as conn:
            raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', self.key(bot_id))
        return self._metadata(self._decode(raw))

    async def propose(self, configuration, *, expected_revision, request_id):
        if (type(expected_revision) is not int or expected_revision < 0
                or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', request_id)):
            raise ValueError('Invalid revision request')
        # Validation precedes transactions. It must not construct a worker.
        validated = self.validate(configuration)
        if configuration.selected_plugins:
            configuration = replace(configuration, selected_plugins=tuple(validated.plugins))
        plaintext = json.dumps(configuration.as_json(), sort_keys=True)
        async with self._locked(configuration.bot_id) as (state, now):
            if state['request_id'] == request_id:
                if self.box.decrypt(state['desired_snapshot']) != plaintext:
                    raise RevisionConflict('Configuration request id conflict')
            else:
                if state['desired_revision'] != expected_revision:
                    raise RevisionConflict('Stale configuration revision')
                state['desired_revision'] += 1
                state['pending_revision'] = state['desired_revision']
                state['configuration_status'] = 'pending'
                state['desired_snapshot'] = self.box.encrypt(plaintext)
                state['request_id'] = request_id
                state['updated_at'] = now
                state['last_error_code'] = None
            result = self._metadata(state)
        return result

    async def confirm_applied(self, bot_id, *, revision, attempt=None, worker_owner=None):
        """Lease-fenced internal acknowledgement; never infer worker success."""
        if not attempt or not worker_owner:
            raise RevisionConflict('Worker ownership required')
        from .reconcile import CloneReconciler
        return await CloneReconciler(self).acknowledge(bot_id, revision=revision,
            attempt=attempt, worker_owner=worker_owner)

    async def record_failure(self, bot_id, *, revision, code):
        if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code):
            raise ValueError('Invalid safe error code')
        async with self._locked(bot_id) as (state, now):
            if (type(revision) is not int or revision != state['pending_revision']
                    or revision != state['desired_revision']):
                raise RevisionConflict('Stale worker failure')
            state['last_failed_revision'] = revision
            state['configuration_status'] = 'failed'
            state['last_error_code'] = code
            state['updated_at'] = now
            result = self._metadata(state)
        return result

    async def pending_configuration(self, bot_id, *, revision):
        """Return only the requested pending snapshot from one SQL read.

        This is a read fence, not a worker lease or acknowledgement. A caller
        must still perform CAS/lease checks when committing applied state.
        """
        if type(revision) is not int or revision <= 0:
            raise ValueError('Invalid configuration revision')
        self._available()
        async with self.db._pool.acquire(timeout=5) as conn:
            raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', self.key(bot_id), timeout=5)
        state = self._decode(raw)
        if (state['desired_revision'] != revision or state['pending_revision'] != revision
                or state['configuration_status'] not in ('pending', 'failed')):
            raise RevisionConflict('Requested configuration is no longer pending')
        fields = json.loads(self.box.decrypt(state['desired_snapshot']))
        fields['selected_plugins'] = tuple(fields.get('selected_plugins', ()))
        configuration = Clone(**fields)
        if configuration.bot_id != bot_id:
            raise RevisionConflict('Configuration identity mismatch')
        try:
            self.validate(configuration)
        except Exception:
            raise RuntimeError('Pending configuration validation failed') from None
        return configuration

    async def applied_configuration(self, bot_id):
        self._available()
        async with self.db._pool.acquire(timeout=5) as conn:
            raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', self.key(bot_id))
        snapshot = self._decode(raw)['applied_snapshot']
        if snapshot is None:
            return None
        fields = json.loads(self.box.decrypt(snapshot))
        fields['selected_plugins'] = tuple(fields.get('selected_plugins', ()))
        return Clone(**fields)
