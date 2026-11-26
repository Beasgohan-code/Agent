"""Apply a revision with actual disposable PostgreSQL ownership in storage tests."""
import json
from types import SimpleNamespace
from agent.modules.clone.store import CloneStore
from agent.modules.clone.reconcile import CloneReconciler


async def reconcile_revision(repo, bot_id, revision):
    reconciler = CloneReconciler(repo)
    # Legacy storage-primitive tests propose directly rather than via the writer.
    async with repo.db._pool.acquire() as conn:
        raw = await conn.fetchval('SELECT value FROM agent_documents WHERE name=$1', repo.key(bot_id))
        state = repo._decode(raw)
        from agent.modules.clone.store import Clone
        config = Clone(**json.loads(repo.box.decrypt(state['desired_snapshot'])))
        await conn.execute("INSERT INTO agent_documents(name,value) VALUES($1,$2::jsonb) ON CONFLICT(name) DO NOTHING",
                           repo.db.name_for('clones'), json.dumps([CloneStore._payload(config, repo.box)]))
    async def apply(configuration):
        async with repo.db._pool.acquire() as conn:
            await conn.execute('''INSERT INTO agent_lease(name,holder,expires_at)
                VALUES($1,'test-worker',EXTRACT(EPOCH FROM clock_timestamp())+60)
                ON CONFLICT(name) DO UPDATE SET holder=EXCLUDED.holder,expires_at=EXCLUDED.expires_at''',
                reconciler.worker_key(bot_id))
        return SimpleNamespace(owner='test-worker')
    try:
        return await reconciler.run(bot_id, revision=revision, apply=apply)
    finally:
        async with repo.db._pool.acquire() as conn:
            await conn.execute('DELETE FROM agent_lease WHERE name=$1 AND holder=$2', reconciler.worker_key(bot_id), 'test-worker')
