"""Real controller routing, tenant-specific registry observations and safe private UI."""
import asyncio
from types import SimpleNamespace

from agent.modules.clone.store import Clone
from agent.platform.manifest import PluginManifest, PluginRegistry
from test_clone import build, TOKEN_A, TOKEN_B, MEMBER, OWNER, FakeMessage, FakeQuery


def private_query(data, uid=MEMBER):
    query = FakeQuery(data, uid=uid)
    query.message.chat.id = uid
    return query


def test_mybots_links_to_individual_dashboard(tmp_path):
    async def scenario():
        ctx, _, handlers = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A, name='First', selected_plugins=('encoder',)))
        message = FakeMessage('/mybots')
        await handlers['mybots'](None, message)
        buttons = [b for row in message.markups[-1].inline_keyboard for b in row]
        assert 'cc:111111111:home' in [b.callback_data for b in buttons]
    asyncio.run(scenario())


def test_dashboards_keep_records_separate_and_hide_secrets(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        store = ctx.clones._store
        store.add(Clone(111111111, MEMBER, TOKEN_A, name='First <bot>', selected_plugins=('encoder',), storage_channel=-100111))
        store.add(Clone(222222222, MEMBER, TOKEN_B, name='Second', selected_plugins=('ai_agent',), ai_api_key='NEVER_RENDER', ai_model='private-model', log_channel=-100222))
        for bot_id, own_name, other_name in ((111111111, 'First', 'Second'), (222222222, 'Second', 'First')):
            query = private_query(f'cc:{bot_id}:home')
            assert await ctx.actions.dispatch(None, query)
            assert query.edits
            text = query.edits[-1][0]
            assert own_name in text and other_name not in text
            assert TOKEN_A not in text and TOKEN_B not in text and 'NEVER_RENDER' not in text
            assert '<bot>' not in text
            assert 'Not observed in this controller' in text
            assert 'Unavailable' in text
            for row in query.edits[-1][1].inline_keyboard:
                assert len(row) <= 2
    asyncio.run(scenario())


def test_control_centre_refuses_other_owners_controller_owner_and_group_origin(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A))
        for uid in (999, OWNER):
            query = private_query('cc:111111111:home', uid)
            await ctx.actions.dispatch(None, query)
            assert not query.edits
            assert query.answers[-1][1]
        query = private_query('cc:111111111:home')
        query.message.chat.id = -100
        await ctx.actions.dispatch(None, query)
        assert not query.edits
        assert query.answers[-1][1]
    asyncio.run(scenario())


def test_live_registry_and_disabled_plugins_match_actual_worker(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A, selected_plugins=('encoder',)))
        registry = PluginRegistry()
        async def handler(*args):
            pass
        registry.register(PluginManifest(slug='encoder', name='Encoder', version='1', description='Encode', commands=('encode',), permissions=('files.read',)), {'encode': handler})
        registry.register(PluginManifest(slug='leech', name='Leech', version='1', description='Download', commands=('leech',)), {'leech': handler})
        registry.disable('leech')
        ctx.clones._running[111111111] = (SimpleNamespace(registry=registry), SimpleNamespace(is_connected=True), 'first_bot')
        query = private_query('cc:111111111:commands:0')
        await ctx.actions.dispatch(None, query)
        assert query.edits
        assert '/encode' in query.edits[-1][0]
        assert '/leech' not in query.edits[-1][0]
        assert 'files.read' in query.edits[-1][0]
        query = private_query('cc:111111111:plugins:0')
        await ctx.actions.dispatch(None, query)
        assert 'Disabled' in query.edits[-1][0]
    asyncio.run(scenario())


def test_deleted_and_malformed_dashboard_callbacks_are_stale(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        for payload in ('cc:111111111:home', 'cc:111111111:commands:-1', 'cc:1:home:extra', 'cc:x:home'):
            query = private_query(payload)
            await ctx.actions.dispatch(None, query)
            assert not query.edits
            assert query.answers[-1][1]
    asyncio.run(scenario())


def test_real_worker_registry_has_builtin_navigation_and_never_inherits_other_clone(tmp_path):
    from agent.bot import AgentBot
    async def scenario():
        ctx, _, _ = build(tmp_path)
        a = Clone(111111111, MEMBER, TOKEN_A, selected_plugins=('encoder',))
        b = Clone(222222222, MEMBER, TOKEN_B, selected_plugins=('postmaker',))
        for clone in (a, b):
            ctx.clones._store.add(clone)
            bot = AgentBot(ctx.clones.settings_for(clone))
            client = bot.build()  # Real Wzgram/registry wiring, no Telegram connection.
            ctx.clones._running[clone.bot_id] = (bot, client, '')
        snapshot = ctx.clones.observe_worker(a.bot_id)
        enabled = {c for p in snapshot['plugins'] if p['enabled'] for c in p['commands']}
        assert enabled == set(ctx.clones._running[a.bot_id][0]._visible_commands())
        assert {'start', 'help', 'ping', 'encode'} <= enabled
        assert 'post' not in enabled
        assert 'post' in {c for p in ctx.clones.observe_worker(b.bot_id)['plugins'] for c in p['commands']}
    asyncio.run(scenario())


def test_dashboard_navigation_pages_and_diagnostics_are_bounded_and_redacted(tmp_path):
    from agent.modules.clone.lifecycle import WorkerState, State
    async def scenario():
        ctx, _, _ = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A, username='first_bot'))
        ctx.clones._states.set(111111111, WorkerState(state=State.FAILED, last_error=TOKEN_A + ' PRIVATE_ERROR'))
        for view in ('home', 'configuration', 'diagnostics', 'commands:0', 'plugins:0'):
            query = private_query(f'cc:111111111:{view}')
            await ctx.actions.dispatch(None, query)
            assert query.edits
            text, keyboard = query.edits[-1]
            assert TOKEN_A not in text and 'PRIVATE_ERROR' not in text
            for row in keyboard.inline_keyboard:
                assert len(row) <= 2
                for button in row:
                    if button.callback_data:
                        assert len(button.callback_data.encode()) <= 64
        before = ctx.clones.record(111111111).as_json()
        query = private_query('cc:111111111:home')
        await ctx.actions.dispatch(None, query)
        assert ctx.clones.record(111111111).as_json() == before
    asyncio.run(scenario())


def test_mybots_failure_summary_never_renders_raw_worker_errors(tmp_path):
    from agent.modules.clone.lifecycle import WorkerState, State
    async def scenario():
        ctx, _, handlers = build(tmp_path)
        ctx.clones._store.add(Clone(111111111, MEMBER, TOKEN_A))
        ctx.clones._states.set(111111111, WorkerState(state=State.FAILED, last_error=TOKEN_A + ' raw-secret'))
        message = FakeMessage('/mybots')
        await handlers['mybots'](None, message)
        assert TOKEN_A not in message.replies[-1]
        assert 'raw-secret' not in message.replies[-1]
        assert 'dashboard diagnostics' in message.replies[-1]
    asyncio.run(scenario())
