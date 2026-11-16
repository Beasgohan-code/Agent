"""Durable lifecycle intent admission; not a configuration writer or worker launcher.

Uses the existing clone-registry lock, revision authority and generation
sequence. No database transaction spans worker I/O. Audit receipts record
admission, never assert that a worker completed an operation.
"""
import json
import re
from dataclasses import replace


class ControlConflict(RuntimeError):
    pass


class CloneControlActions:
    def __init__(self, store):
        self.store = store

    async def admit(self, bot_id, action, *, actor_id, expected_revision, expected_generation, request_id):
        if (type(bot_id) is not int or bot_id <= 0 or type(actor_id) is not int or actor_id <= 0
                or type(expected_revision) is not int or expected_revision <= 0
                or type(expected_generation) is not int or expected_generation < 0
                or action not in ('start', 'stop', 'restart', 'reconcile')
                or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', request_id)):
            raise ControlConflict('Invalid lifecycle request.')
        store, db = self.store, self.store._db
        try:
            if db is None or not db.connected or db._pool is None or not store.encrypted():
                raise ControlConflict('Encrypted PostgreSQL lifecycle authority is unavailable.')
            if 'clones' in getattr(db, '_pending', {}):
                raise ControlConflict('Clone state has an unconfirmed write.')
            repo = store.configuration.repository
            async with db._pool.acquire(timeout=5) as conn:
                async with conn.transaction():
                    key = db.name_for('clones')
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
                    raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key, timeout=5)
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(raw, list):
                        raise ControlConflict('Clone registry is unavailable.')
                    items = store._decode(raw)
                    clone = items.get(bot_id)
                    if len(items) != len(raw) or clone is None or clone.owner_id != actor_id:
                        raise ControlConflict('Clone ownership changed or access was refused.')
                    revision_key = repo.key(bot_id)
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', revision_key, timeout=5)
                    state = repo._decode(await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', revision_key, timeout=5))
                    receipt_key = db.name_for(f'clone_control:{bot_id}:{request_id}')
                    if await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', receipt_key, timeout=5) is not None:
                        raise ControlConflict('This action was already admitted. Refresh to inspect its result.')
                    if (clone.lifecycle_generation != expected_generation or clone.configuration_revision != expected_revision
                            or state['desired_revision'] != expected_revision):
                        raise ControlConflict('Clone configuration or lifecycle changed. Refresh before retrying.')
                    generation = await store._next_generation(conn, bot_id, clone.lifecycle_generation)
                    assignment = replace(clone, disabled=(action == 'stop'), lifecycle_generation=generation)
                    items[bot_id] = assignment
                    await conn.execute('UPDATE agent_documents SET value=$2::jsonb,updated_at=now() WHERE name=$1',
                        key, json.dumps([store._payload(c, store._box) for c in items.values()]), timeout=5)
                    receipt = dict(status='admitted', action=action, actor_id=actor_id, bot_id=bot_id, request_id=request_id,
                                   revision=expected_revision, previous_generation=expected_generation,
                                   assigned_generation=generation,
                                   at=float(await conn.fetchval('SELECT EXTRACT(EPOCH FROM clock_timestamp())')))
                    await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)',
                                       receipt_key, json.dumps(receipt), timeout=5)
            store._items = items
            return assignment
        except ControlConflict:
            raise
        except Exception:
            raise ControlConflict('Lifecycle intent was not confirmed. Refresh before retrying.') from None
