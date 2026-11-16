"""Compact directory filters canonical owner intent, never inferred fleet uptime."""
import asyncio
from agent.modules.clone.store import Clone
from test_clone import build, MEMBER, OWNER, TOKEN_A
from test_clone_control_centre import private_query


def test_directory_pagination_filter_isolation_and_mobile_navigation(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        store = ctx.clones._store
        for i in range(7):
            store.add(Clone(111111111+i, MEMBER, TOKEN_A, name=f'Own {i}', disabled=i % 2 == 0))
        store.add(Clone(222222222, OWNER, TOKEN_A, name='FOREIGN_SECRET'))
        for mode, expected_count in (('all', 7), ('stopped', 4), ('eligible', 3)):
            q = private_query(f'cc:list:{mode}:0')
            await ctx.actions.dispatch(None, q)
            assert q.edits
            text, keyboard = q.edits[-1]
            assert f'{expected_count} matching' in text
            assert 'FOREIGN_SECRET' not in text and TOKEN_A not in text
            assert 'fleet-wide' in text
            assert all(len(row) <= 2 for row in keyboard.inline_keyboard)
            data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
            if mode == 'all':
                assert 'cc:111111117:home' not in data
        next_page = private_query('cc:list:all:1')
        await ctx.actions.dispatch(None, next_page)
        assert 'cc:111111117:home' in str(next_page.edits[-1][1])
        assert 'cc:list:all:0' in str(next_page.edits[-1][1])
        own = private_query('cc:111111111:home')
        await ctx.actions.dispatch(None, own)
        assert 'cc:list:all:0' in str(own.edits[-1][1])
    asyncio.run(scenario())


def test_directory_empty_foreign_owner_group_and_malformed(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A))
        q = private_query('cc:list:all:0', OWNER)
        await ctx.actions.dispatch(None, q)
        assert 'No clones match' in q.edits[-1][0]
        assert '111111111' not in q.edits[-1][0]
        for payload in ('cc:list:all:999', 'cc:list:bogus:0', 'cc:list:all:-1', 'cc:list:all:0:extra'):
            q = private_query(payload)
            await ctx.actions.dispatch(None, q)
            assert not q.edits and q.answers[-1][1]
        q = private_query('cc:list:all:0')
        q.message.chat.id = -100
        await ctx.actions.dispatch(None, q)
        assert not q.edits and q.answers[-1][1]
    asyncio.run(scenario())


def test_directory_postgresql_refresh_deletion_and_outage(tmp_path):
    import os
    import uuid
    import pytest
    from agent.modules.clone.control_centre import CloneControlCentre
    from agent.modules.clone.manager import CloneManager
    from agent.modules.clone.store import CloneStore
    from agent.platform.db import Database
    from agent.platform.secrets import SecretBox
    from test_atomic_clones import KEY
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    async def scenario():
        scope = 'directory:' + uuid.uuid4().hex
        dbs = [Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope) for _ in range(2)]
        try:
            for db in dbs:
                assert await db.connect()
            ctx, _, _ = build(tmp_path / 'ctx')
            stores = [CloneStore(tmp_path / str(i), db=db, box=SecretBox(KEY)) for i, db in enumerate(dbs)]
            managers = [CloneManager(ctx.settings, store) for store in stores]
            manager = managers[1]
            centre = CloneControlCentre(ctx, manager)
            await stores[0].aadd(Clone(111111111, MEMBER, TOKEN_A, name='Saved A'), owner_limit=3, total_limit=5)
            async def show(mode):
                q = private_query(f'cc:list:{mode}:0')
                await centre.press(None, q, q.data.split(':', 1)[1])
                return q
            assert 'Saved A' in (await show('all')).edits[-1][0]
            found, keys = await centre.render_directory(MEMBER, 'all', 0, 'saved a')
            assert 'Saved A' in found
            foreign, _ = await centre.render_directory(OWNER, 'all', 0, 'saved a')
            assert 'No clones match' in foreign
            assert all(len(b.callback_data.encode()) <= 64 for row in keys.inline_keyboard for b in row if b.callback_data)
            await stores[0].afence(111111111, disabled=True)
            assert 'No clones match' in (await show('eligible')).edits[-1][0]
            assert 'Saved A' in (await show('stopped')).edits[-1][0]
            await stores[0].aremove(111111111)
            assert 'No clones match' in (await show('all')).edits[-1][0]
            removed, _ = await centre.render_directory(MEMBER, 'all', 0, 'saved a')
            assert 'No clones match' in removed
            await dbs[1].close()
            q = await show('all')
            assert not q.edits and q.answers[-1][1]
        finally:
            for db in dbs:
                await db.close()
    asyncio.run(scenario())
