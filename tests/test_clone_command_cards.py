"""Command detail cards follow the current clone registry, not saved profiles."""
import asyncio
from types import SimpleNamespace
from agent.modules.clone.store import Clone
from agent.platform.manifest import PluginManifest, PluginRegistry
from test_clone import build, MEMBER, OWNER, TOKEN_A, TOKEN_B
from test_clone_control_centre import private_query


def test_command_cards_copy_context_and_disabled_staleness(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A))
        ctx.clones._store.add(Clone(222222222, MEMBER, TOKEN_B))
        registry = PluginRegistry()
        async def handler(*args):
            pass
        registry.register(PluginManifest(slug='encoder', name='Encoder', version='1', description='Encode',
            commands=('encode',), permissions=('files.read',), dependencies=('base',), scope='private'), {'encode': handler})
        ctx.clones._running[111111111] = (SimpleNamespace(registry=registry), SimpleNamespace(is_connected=True), 'test_bot')
        listing = private_query('cc:111111111:commands:0')
        await ctx.actions.dispatch(None, listing)
        assert 'cc:111111111:command:encode' in str(listing.edits[-1][1])
        q = private_query('cc:111111111:command:encode')
        await ctx.actions.dispatch(None, q)
        assert q.edits
        text, keyboard = q.edits[-1]
        assert 'files.read' in text and 'base' in text and 'Encoder' in text
        copies = [b.copy_text.text for row in keyboard.inline_keyboard for b in row if b.copy_text]
        assert copies == ['/encode']
        assert 'cc:111111111:commands:0' in str(keyboard)
        assert TOKEN_A not in text and TOKEN_B not in text
        for uid in (OWNER, 999):
            foreign = private_query(q.data, uid)
            await ctx.actions.dispatch(None, foreign)
            assert not foreign.edits and foreign.answers[-1][1]
        for data in ('cc:222222222:command:encode', 'cc:111111111:command:missing', 'cc:111111111:command:Encode'):
            absent = private_query(data)
            await ctx.actions.dispatch(None, absent)
            assert not absent.edits and absent.answers[-1][1]
        group = private_query(q.data)
        group.message.chat.id = -100
        await ctx.actions.dispatch(None, group)
        assert not group.edits and group.answers[-1][1]
        assert all(len(row) <= 2 for row in keyboard.inline_keyboard)
        assert all(len(b.callback_data.encode()) <= 64 for row in keyboard.inline_keyboard for b in row if b.callback_data)
        registry.disable('encoder')
        stale = private_query(q.data)
        await ctx.actions.dispatch(None, stale)
        assert not stale.edits and stale.answers[-1][1]
        disabled_list = private_query(listing.data)
        await ctx.actions.dispatch(None, disabled_list)
        assert 'command:encode' not in str(disabled_list.edits[-1][1])
    asyncio.run(scenario())
