"""Command scope filters use manifest scope, not guessed permissions."""
import asyncio
from types import SimpleNamespace
from agent.modules.clone.store import Clone
from agent.platform.manifest import PluginManifest, PluginRegistry
from test_clone import build, MEMBER, TOKEN_A
from test_clone_control_centre import private_query


def test_scope_filters_paginate_and_exclude_disabled(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A))
        registry = PluginRegistry()
        async def handler(*args):
            pass
        for slug, scope, commands in (('private_tools', 'private', tuple(f'tool{i}' for i in range(8))),
                                       ('groups', 'group', ('ban',)), ('shared', 'all', ('ping',)),
                                       ('off', 'group', ('hidden',))):
            registry.register(PluginManifest(slug=slug, name=slug, version='1', description='', scope=scope, commands=commands), {cmd: handler for cmd in commands})
        registry.disable('off')
        ctx.clones._running[111111111] = (SimpleNamespace(registry=registry), SimpleNamespace(is_connected=True), '')
        for scope in ('private', 'group', 'all'):
            q = private_query(f'cc:111111111:cmds:{scope}:0')
            await ctx.actions.dispatch(None, q)
            assert q.edits
            text, keys = q.edits[-1]
            assert '/hidden' not in text
            assert 'Declared scope filter' in text
            if scope == 'group':
                assert '/ban' in text and '/ping' in text and '/tool0' not in text
            if scope == 'private':
                assert '/ban' not in text
                assert 'cc:111111111:cmds:private:1' in str(keys)
            assert all(len(row) <= 2 for row in keys.inline_keyboard)
        page = private_query('cc:111111111:cmds:private:1')
        await ctx.actions.dispatch(None, page)
        assert '/ping' in page.edits[-1][0]
        assert 'cc:111111111:cmds:private:0' in str(page.edits[-1][1])
        for data in ('cc:111111111:cmds:bogus:0', 'cc:111111111:cmds:group:9', 'cc:111111111:cmds:group:-1'):
            q = private_query(data)
            await ctx.actions.dispatch(None, q)
            assert not q.edits and q.answers[-1][1]
        grouped = private_query('cc:111111111:cmds:group:0')
        grouped.message.chat.id = -100
        await ctx.actions.dispatch(None, grouped)
        assert not grouped.edits and grouped.answers[-1][1]
        registry.disable('shared')
        changed = private_query('cc:111111111:cmds:group:0')
        await ctx.actions.dispatch(None, changed)
        assert '/ping' not in changed.edits[-1][0]
        q = private_query('cc:111111111:cmds:group:0', 999)
        await ctx.actions.dispatch(None, q)
        assert not q.edits and q.answers[-1][1]
    asyncio.run(scenario())
