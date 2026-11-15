"""Selection edits, persistence and failure boundaries through existing runtime."""
import asyncio
from unittest.mock import Mock
import pytest
from agent.modules.clone.store import Clone, CloneStore
from agent.modules.clone.manager import CloneError
from agent.modules.clone.catalog import plan_selection
from agent.platform.selection import SelectionError
from test_clone import build, TOKEN_A, MEMBER, FakeMessage
from test_clone_setup import identity_step, query


def test_arbitrary_selection_persistence_and_recovery_validation(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        store = ctx.clones._store
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
                       selected_plugins=('encoder', 'postmaker'))
        store.add(record)
        restored = CloneStore(store.path.parent, box=store._box)
        assert restored.get(record.bot_id).selected_plugins == ('encoder', 'postmaker')
        # Existing restart/recovery path rejects persisted corruption before factory.
        store.update(record.bot_id, selected_plugins=('encoder', 'ops'))
        factory = Mock(side_effect=AssertionError('must not construct worker'))
        ctx.clones._factory = factory
        before = store.path.read_bytes()
        assert await ctx.clones.restore() == ()
        factory.assert_not_called()
        assert store.path.read_bytes() == before
        assert not ctx.clones.running()
        assert ctx.clones.state(record.bot_id).last_error
    asyncio.run(scenario())


def test_draft_edits_are_validated_before_mutation_and_clear_unused_secrets(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        wizard.select_plugins(state, ('postmaker', 'encoder', 'encoder'))
        assert state.selected_plugins == ('encoder', 'postmaker')
        state.ai_api_key, state.ai_model = 'unused-secret', 'unused-model'
        with pytest.raises(SelectionError):
            wizard.select_plugins(state, ('ops',))
        assert state.selected_plugins == ('encoder', 'postmaker')
        assert state.ai_api_key == 'unused-secret'
        wizard.select_plugins(state, ('encoder',))
        assert not state.ai_api_key and not state.ai_model
        assert not wizard.store.all()
        assert plan_selection((' MODERATION ',)) == ('moderation',)
    asyncio.run(scenario())


def test_existing_preset_can_be_edited_and_created_as_arbitrary_combination(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':encoder')
        await wizard.receive(None, FakeMessage('skip'))
        assert state.step == 'confirm'
        await wizard.press(None, query(state), state.nonce + ':edit_plugins')
        await wizard.press(None, query(state), state.nonce + ':toggle:postmaker')
        assert state.selected_plugins == ('encoder', 'postmaker')
        await wizard.press(None, query(state), state.nonce + ':apply')
        await wizard.receive(None, FakeMessage('skip'))
        await wizard.press(None, query(state), state.nonce + ':create')
        record = wizard.store.all()[0]
        assert record.selected_plugins == ('encoder', 'postmaker')
        assert ctx.clones.is_running(record.bot_id)
        await ctx.clones.stop(record.bot_id)
    asyncio.run(scenario())


def test_invalid_credential_start_does_not_construct_worker_or_change_record(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        store = ctx.clones._store
        record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
                       selected_plugins=('ai_agent',), ai_api_key='malformed', ai_model='model')
        store.add(record)
        before = store.path.read_bytes()
        factory = Mock()
        ctx.clones._factory = factory
        with pytest.raises(CloneError):
            await ctx.clones.start(record)
        factory.assert_not_called()
        assert before == store.path.read_bytes()
        assert not ctx.clones.running()
    asyncio.run(scenario())


def test_confirmation_revalidates_persisted_intent_before_database_write(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':encoder')
        await wizard.receive(None, FakeMessage('skip'))
        # Simulate corrupted/stale draft, bypassing the safe editing API.
        state.selected_plugins = ('encoder', 'ops')
        add = Mock(side_effect=AssertionError('must not write'))
        wizard.store.aadd = add
        factory = Mock()
        ctx.clones._factory = factory
        await wizard.press(None, query(state), state.nonce + ':create')
        add.assert_not_called()
        factory.assert_not_called()
        assert not wizard.store.all()
    asyncio.run(scenario())


def test_confirmation_detects_concurrent_draft_changes_during_validation(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        wizard, state = await identity_step(ctx)
        await wizard.press(None, query(state), state.nonce + ':encoder')
        await wizard.receive(None, FakeMessage('skip'))
        original = wizard.api

        async def changed_api(*args, **kwargs):
            result = await original(*args, **kwargs)
            state.selected_plugins = ('postmaker',)
            return result

        wizard.api = changed_api
        await wizard.press(None, query(state), state.nonce + ':create')
        assert not wizard.store.all()
        assert not ctx.clones.running()
    asyncio.run(scenario())
