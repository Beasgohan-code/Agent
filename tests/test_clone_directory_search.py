"""Owner-scoped directory search survives filters without server-local sessions."""
import asyncio
from agent.modules.clone.store import Clone
from test_clone import build, MEMBER, OWNER, TOKEN_A, FakeMessage
from test_clone_control_centre import private_query


def test_mybots_search_and_filter_round_trip(tmp_path):
    async def scenario():
        ctx, _, handlers = build(tmp_path)
        for i in range(7):
            ctx.clones._store.add(Clone(111111111+i, MEMBER, TOKEN_A, name=f'Blue {i}', username=f'blue_{i}_bot', disabled=i % 2 == 0))
        ctx.clones._store.add(Clone(222222222, OWNER, TOKEN_A, name='Blue FOREIGN'))
        for term in ('Blue', '@blue_0_bot', '111111111'):
            m = FakeMessage('/mybots ' + term)
            await handlers['mybots'](None, m)
            assert 'Search' in m.replies[-1] and 'FOREIGN' not in m.replies[-1]
            assert TOKEN_A not in m.replies[-1]
        m = FakeMessage('/mybots Blue')
        await handlers['mybots'](None, m)
        data = [b.callback_data for row in m.markups[-1].inline_keyboard for b in row]
        nxt = next(d for d in data if d.startswith('cc:list:all:1:'))
        q = private_query(nxt)
        await ctx.actions.dispatch(None, q)
        assert 'Blue 6' in q.edits[-1][0]
        filters = [b.callback_data for row in q.edits[-1][1].inline_keyboard for b in row]
        stop = next(d for d in filters if d.startswith('cc:list:stopped:0:'))
        filtered = private_query(stop)
        await ctx.actions.dispatch(None, filtered)
        assert '4 matching' in filtered.edits[-1][0]
        assert 'Blue 1' not in filtered.edits[-1][0]
        assert 'cc:list:all:0' in str(filtered.edits[-1][1])
        assert all(len(d.encode()) <= 64 for d in filters if d)
    asyncio.run(scenario())


def test_search_bounds_escaping_group_and_invalid_callback(tmp_path):
    async def scenario():
        ctx, _, handlers = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A, name='<b>Test</b>'))
        for text in ('/mybots ' + 'a'*25, '/mybots ' + '🙂'*7):
            m = FakeMessage(text)
            await handlers['mybots'](None, m)
            assert '24 UTF-8 bytes' in m.replies[-1]
            assert not m.markups or m.markups[-1] is None
        m = FakeMessage('/mybots <b>')
        await handlers['mybots'](None, m)
        assert '<b>Test</b>' not in m.replies[-1]
        assert '&lt;b&gt;' in m.replies[-1]
        group = FakeMessage('/mybots Test')
        group.chat.id = -100
        await handlers['mybots'](None, group)
        assert not group.markups or group.markups[-1] is None
        for payload in ('cc:list:all:0:_', 'cc:list:all:0:' + 'A'*34, 'cc:list:all:0:===='):
            q = private_query(payload)
            await ctx.actions.dispatch(None, q)
            assert not q.edits and q.answers[-1][1]
    asyncio.run(scenario())
