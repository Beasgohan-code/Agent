"""Awaited link operations fail closed and serialize across PostgreSQL clients."""
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from agent.platform.db import Database
from agent.platform.links import LinkStore, LinkRecord, LinkError


def test_database_sync_link_paths_refuse_background_writes(tmp_path):
    store = LinkStore(tmp_path, 'secret', db=SimpleNamespace(connected=False))
    for operation, args in [('create', ('file', 1)), ('resolve', ('token',)), ('consume', ('token',)),
                            ('revoke', ('token',)), ('owned', (1,)), ('purge_expired', ())]:
        with pytest.raises(LinkError, match='Awaited'):
            getattr(store, operation)(*args)
    assert not list(tmp_path.glob('*.json'))


def test_database_outage_never_uses_cached_grants(tmp_path):
    async def scenario():
        store = LinkStore(tmp_path, 'secret', db=SimpleNamespace(connected=False, _pool=None))
        with pytest.raises(LinkError, match='unavailable'):
            await store.acreate('file', 1)
        with pytest.raises(LinkError, match='unavailable'):
            await store.aconsume('token')
        assert not list(tmp_path.glob('*.json'))
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable Database required')
def test_pg_competing_consumers_revocation_persistence_and_tenant_isolation(tmp_path):
    async def scenario():
        scope = 'links-test:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True),
               Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True),
               Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope+':clone', required=True)]
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            stores = [LinkStore(tmp_path / str(i), 'secret', db=db) for i, db in enumerate(dbs)]
            record = await stores[0].acreate('file', 1, max_uses=3)
            async def consume(i):
                try:
                    await stores[i % 2].aconsume(record.token)
                    return True
                except LinkError as error:
                    assert str(error) == 'link used up'
                    return False
            outcomes = await asyncio.gather(*(consume(i) for i in range(30)))
            assert sum(outcomes) == 3
            assert (await stores[1].aowned(1))[0].uses == 3
            assert not await stores[2].aowned(1)
            with pytest.raises(LinkError, match='unavailable'):
                await stores[2].aresolve(record.token)
            other = await stores[0].acreate('file', 1)
            assert await stores[1].arevoke(other.token, owner_id=2) is False
            assert await stores[1].arevoke(other.token, owner_id=1) is True
            with pytest.raises(LinkError, match='revoked'):
                await stores[0].aconsume(other.token)
            fresh = LinkStore(tmp_path / 'fresh', 'secret', db=dbs[1])
            with pytest.raises(LinkError, match='revoked'):
                await fresh.aresolve(other.token)
            async with dbs[0]._pool.acquire() as conn:
                raw = json.loads(await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', dbs[0].name_for('links')))
            assert raw[record.token]['uses'] == 3
            assert 'links' not in dbs[0]._pending
            assert not list(tmp_path.rglob('*.json'))
        finally:
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute('DELETE FROM agent_documents WHERE name=$1', db.name_for('links'))
                await db.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable Database required')
def test_pg_legacy_document_preserves_grants_and_purge_does_not_resurrect(tmp_path):
    async def scenario():
        db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='links-legacy:'+uuid.uuid4().hex, required=True)
        try:
            assert await db.connect()
            store = LinkStore(tmp_path, 'secret', db=db)
            payload = f'file.1.{int(time.time())+3600}'
            token = payload + '.' + store._sign(payload)
            legacy = LinkRecord(token, 'file', 1, time.time(), time.time()+3600, uses=1, max_uses=2)
            async with db._pool.acquire() as conn:
                await conn.execute('INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb)', db.name_for('links'), json.dumps({token:asdict(legacy)}))
            assert (await store.aconsume(token)).uses == 2
            with pytest.raises(LinkError, match='used up'):
                await LinkStore(tmp_path / 'stale', 'secret', db=db).aconsume(token)
            expired = await store.acreate('file', 1, ttl_hours=0)
            assert await store.apurge_expired() == 1
            with pytest.raises(LinkError, match='unavailable'):
                await store.aresolve(expired.token)
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name=$1', db.name_for('links'))
            await db.close()
    asyncio.run(scenario())


def test_request_id_consumption_survives_reload(tmp_path):
    store = LinkStore(tmp_path, 'secret')
    record = store.create('file', 1)
    store.consume(record.token, request_id='7:7:10')
    reloaded = LinkStore(tmp_path, 'secret')
    with pytest.raises(LinkError, match='already recorded'):
        reloaded.consume(record.token, request_id='7:7:10')
    assert reloaded.get(record.token).uses == 1


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable Database required')
def test_pg_request_id_is_atomic_across_instances_and_expiry(tmp_path):
    async def scenario():
        scope = 'redemption-security:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
                await db.load()
            stores = [LinkStore(tmp_path / str(i), 'secret', db=db) for i, db in enumerate(dbs)]
            grant = await stores[0].acreate('file', 1)
            async def claim(index):
                try:
                    await stores[index % 2].aconsume(grant.token, request_id='7:7:10')
                    return True
                except LinkError as error:
                    assert str(error) == 'Redemption request already recorded'
                    return False
            assert sum(await asyncio.gather(*(claim(i) for i in range(20)))) == 1
            fresh = LinkStore(tmp_path / 'fresh', 'secret', db=dbs[1])
            with pytest.raises(LinkError, match='already recorded'):
                await fresh.aconsume(grant.token, request_id='7:7:10')
            assert (await fresh.aowned(1))[0].uses == 1
            expired = await stores[0].acreate('file', 1, ttl_hours=0)
            with pytest.raises(LinkError, match='expired'):
                await fresh.aconsume(expired.token, request_id='7:7:11')
            assert next(r for r in await fresh.aowned(1) if r.token == expired.token).uses == 0
        finally:
            for db in dbs:
                if db.connected:
                    async with db._pool.acquire() as conn:
                        await conn.execute('DELETE FROM agent_documents WHERE name=$1', db.name_for('links'))
                await db.close()
    asyncio.run(scenario())
