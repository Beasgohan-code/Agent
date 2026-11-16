"""Canonical desired-configuration writes. No worker construction or acknowledgement.

Lock order: tenant clone registry, then per-clone revision. Desired registry row,
encrypted snapshot, pending revision and durable request receipt commit together.
"""
import json
import re
from dataclasses import replace

from .revisions import CloneConfigurationRevisions, RevisionConflict

CONFIG_FIELDS = frozenset({'profile', 'selected_plugins', 'ai_api_key', 'ai_model',
                           'assistant_session', 'log_channel', 'storage_channel', 'name'})


class ConfigurationWriteError(RuntimeError):
    pass


class CloneConfigurationWriter:
    def __init__(self, store, validate, *, controller_owner_id=None):
        self.store = store
        self.controller_owner_id = controller_owner_id
        self.repository = CloneConfigurationRevisions(store._db, box=store._box, validate=validate)

    async def read(self, bot_id):
        return await self.repository.read(bot_id)

    async def _persist(self, conn, configuration, *, expected_revision, request_id, identity):
        repo = self.repository
        key = repo.key(configuration.bot_id)
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
        raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key, timeout=5)
        state = repo._decode(raw)
        receipt_key = self.store._db.name_for(f'clone_configuration_request:{configuration.bot_id}:{request_id}')
        receipt = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', receipt_key, timeout=5)
        if receipt is not None:
            receipt = json.loads(receipt) if isinstance(receipt, str) else receipt
            if repo.box.decrypt(receipt['request']) != identity:
                raise RevisionConflict('Configuration request id conflict')
            return None, receipt['result']
        if state['desired_revision'] != expected_revision:
            raise RevisionConflict('Stale configuration revision')
        try:
            from . import profiles
            if configuration.profile not in profiles.ORDER:
                raise ValueError
            validated = repo.validate(configuration)
            if configuration.selected_plugins:
                configuration = replace(configuration, selected_plugins=tuple(validated.plugins))
        except Exception:
            raise ConfigurationWriteError('Invalid clone configuration') from None
        revision = expected_revision + 1
        configuration = replace(configuration, configuration_revision=revision)
        state.update(desired_revision=revision, pending_revision=revision,
                     configuration_status='pending', desired_snapshot=repo.box.encrypt(json.dumps(configuration.as_json(), sort_keys=True)),
                     request_id=request_id, last_error_code=None,
                     updated_at=float(await conn.fetchval('SELECT EXTRACT(EPOCH FROM clock_timestamp())')))
        result = repo._metadata(state)
        for name, value in ((key, state), (receipt_key, {'request': repo.box.encrypt(identity), 'result': result})):
            await conn.execute('''INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)
                ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value,updated_at=now()''', name, json.dumps(value), timeout=5)
        return configuration, result

    async def write(self, bot_id, *, actor_id, expected_revision, request_id, changes, owner_only=False, expected_generation=None):
        if (type(expected_revision) is not int or expected_revision < 0 or type(actor_id) is not int
                or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', request_id)
                or not isinstance(changes, dict) or not changes or set(changes) - CONFIG_FIELDS):
            raise ConfigurationWriteError('Invalid configuration request')
        if type(owner_only) is not bool or (expected_generation is not None and
                (type(expected_generation) is not int or expected_generation <= 0)):
            raise ConfigurationWriteError('Invalid configuration guard')
        store = self.store
        try:
            self.repository._available()
            if 'clones' in getattr(store._db, '_pending', {}):
                raise ConfigurationWriteError('Clone state has an unconfirmed legacy write')
            identity = json.dumps({'actor': actor_id, 'expected': expected_revision, 'changes': changes}, sort_keys=True)
            async with store._db._pool.acquire(timeout=5) as conn:
                async with conn.transaction():
                    key = store._db.name_for('clones')
                    await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key, timeout=5)
                    raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1 FOR UPDATE', key, timeout=5)
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(raw, list):
                        raise ConfigurationWriteError('Clone registry unavailable')
                    items = store._decode(raw)
                    if len(items) != len(raw) or bot_id not in items or actor_id not in (items[bot_id].owner_id, self.controller_owner_id):
                        raise ConfigurationWriteError('Clone configuration access refused')
                    if owner_only and actor_id != items[bot_id].owner_id:
                        raise ConfigurationWriteError('Only the saved clone owner may change this configuration')
                    if expected_generation is not None and items[bot_id].lifecycle_generation != expected_generation:
                        raise ConfigurationWriteError('Lifecycle changed; refresh configuration before saving')
                    configuration, result = await self._persist(conn, replace(items[bot_id], **changes),
                        expected_revision=expected_revision, request_id=request_id, identity=identity)
                    if configuration is not None:
                        items[bot_id] = configuration
                        await conn.execute('''UPDATE agent_documents SET value=$2::jsonb,updated_at=now() WHERE name=$1''',
                            key, json.dumps([store._payload(c, store._box) for c in items.values()]), timeout=5)
            store._items = items
            return result
        except (RevisionConflict, ConfigurationWriteError):
            raise
        except Exception:
            raise ConfigurationWriteError('Configuration result not confirmed; inspect revision before retrying') from None
