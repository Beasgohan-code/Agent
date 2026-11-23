"""Group execution and cleanup must not affect core or another group's jobs."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform.actions import ActionRouter
from agent.platform.execution import PluginGate, REGISTERING, GROUP_EXECUTION
from agent.platform.jobs import JobQueue, JobState


def message(group=-100):
    return SimpleNamespace(chat=SimpleNamespace(id=group), reply=AsyncMock())


def gate():
    access = SimpleNamespace(eligible=AsyncMock(return_value=True))
    runtime = SimpleNamespace(wants_disabled=lambda slug: False,
                              registry=SimpleNamespace(is_enabled=lambda slug: True))
    jobs = JobQueue(concurrency=4)
    return PluginGate(access, runtime, jobs), access, jobs


def test_unapproved_command_refused_and_core_never_queries_catalog():
    async def scenario():
        execution, access, _ = gate()
        access.eligible.return_value = False
        handler = AsyncMock()
        update = message()
        await execution.wrap('encoder', handler)(None, update)
        handler.assert_not_awaited()
        assert update.reply.await_count == 1
        access.eligible.reset_mock()
        await execution.wrap('moderation', handler)(None, update)
        handler.assert_awaited_once()
        access.eligible.assert_not_awaited()
    asyncio.run(scenario())


def test_callback_eligibility_rechecked_on_every_press():
    async def scenario():
        execution, access, _ = gate()
        router = ActionRouter()
        router.gate = execution
        handler = AsyncMock()
        token = REGISTERING.set('music')
        try:
            router.register('transport', handler)
        finally:
            REGISTERING.reset(token)
        query = SimpleNamespace(data='transport:pause', message=message(), answer=AsyncMock())
        await router.dispatch(None, query)
        handler.assert_awaited_once()
        access.eligible.return_value = False
        await router.dispatch(None, query)
        assert handler.await_count == 1
        query.answer.assert_awaited_once()
        assert access.eligible.await_count == 2
    asyncio.run(scenario())


def test_private_compatibility_does_not_use_group_slots():
    async def scenario():
        execution, access, _ = gate()
        handler = AsyncMock()
        await execution.wrap('filestore', handler)(None, message(22))
        handler.assert_awaited_once()
        access.eligible.assert_not_awaited()
    asyncio.run(scenario())


def test_optional_exception_is_contained_and_execution_context_reset():
    async def scenario():
        execution, _, _ = gate()
        handler = AsyncMock(side_effect=RuntimeError('plugin bug'))
        update = message()
        await execution.wrap('encoder', handler)(None, update)
        assert 'moderation remains available' in update.reply.await_args.args[0]
        assert GROUP_EXECUTION.get() is None
    asyncio.run(scenario())


def test_revocation_cancels_only_owned_group_jobs_and_calls_cleanup():
    async def scenario():
        execution, access, jobs = gate()
        wait = asyncio.Event()
        async def runner(job):
            await wait.wait()
        async def submit(_client, update):
            return jobs.submit('encoder', 22, runner)
        wrapped = execution.wrap('encoder', submit)
        first = await wrapped(None, message(-100))
        second = await wrapped(None, message(-200))
        await asyncio.sleep(0)
        cleanup = AsyncMock()
        execution.cleanup_hook('encoder', cleanup)
        access.eligible.side_effect = lambda group, slug: group != -100
        await execution.reconcile()
        assert first.group_id == -100 and first.state is JobState.CANCELLED
        assert second.group_id == -200 and second.state is JobState.RUNNING
        cleanup.assert_awaited_once_with(-100)
        await jobs.shutdown()
    asyncio.run(scenario())


def test_queued_job_rechecks_approval_before_starting():
    async def scenario():
        execution, access, jobs = gate()
        runner = AsyncMock()
        for _ in range(4):
            await jobs._limit.acquire()
        async def submit(_client, update):
            return jobs.submit('encoder', 22, runner)
        job = await execution.wrap('encoder', submit)(None, message())
        access.eligible.return_value = False
        jobs._limit.release()
        await job.task
        assert job.state is JobState.CANCELLED
        runner.assert_not_awaited()
    asyncio.run(scenario())


def test_database_outage_refuses_optional_execution_without_affecting_core():
    async def scenario():
        execution, access, _ = gate()
        access.eligible.side_effect = RuntimeError('db unavailable')
        handler = AsyncMock()
        await execution.wrap('encoder', handler)(None, message())
        handler.assert_not_awaited()
        await execution.wrap('security', handler)(None, message())
        handler.assert_awaited_once()
    asyncio.run(scenario())


def test_cleanup_cancels_owned_invocation_not_dispatcher():
    async def scenario():
        execution, _, _ = gate()
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def handler(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        dispatcher = asyncio.create_task(execution.wrap('music', handler)(None, message()))
        await entered.wait()
        await execution.cleanup(-100, 'music')
        await dispatcher
        assert not dispatcher.cancelled()
        assert cancelled.is_set()
        assert not execution._running
    asyncio.run(scenario())


def test_optional_build_failure_does_not_remove_moderation(tmp_path, monkeypatch):
    from agent.bot import AgentBot
    from agent.config import Settings
    from agent.modules import leech
    from agent.platform.policy import GROUP_CORE
    def broken(ctx):
        ctx.actions.register('broken-plugin-route', AsyncMock())
        raise RuntimeError('optional build failure')
    monkeypatch.setattr(leech, 'build', broken)
    bot = AgentBot(Settings.from_env({
        'BOT_TOKEN': '123456789:AAHfakeTokenValueForTests_1234567890abc', 'API_ID': '123', 'API_HASH': 'a' * 32,
        'DATA_DIR': str(tmp_path), 'PLUGINS': 'leech',
    }))
    bot.build()
    assert set(GROUP_CORE) <= {manifest.slug for manifest in bot.registry.manifests()}
    assert 'ban' in bot.registry.active_commands()
    assert 'leech' not in bot.registry.active_commands()
    assert not bot.actions.handles('broken-plugin-route:anything')


@pytest.mark.parametrize('approval', [1, 'true', object(), None])
@pytest.mark.parametrize('surface', ['command', 'callback', 'listener'])
def test_optional_surfaces_deny_nonboolean_group_approval(approval, surface):
    async def scenario():
        execution, access, jobs = gate()
        access.eligible.return_value = approval
        handler = AsyncMock()
        update = message()
        callback = surface == 'callback'
        if callback:
            update = SimpleNamespace(message=update, answer=AsyncMock())
        await execution.wrap('encoder', handler, callback=callback, silent=surface == 'listener')(None, update)
        handler.assert_not_awaited()
        assert not execution._seen and not execution._running
        assert GROUP_EXECUTION.get() is None
        if callback:
            update.answer.assert_awaited_once()
        await jobs.shutdown()
    asyncio.run(scenario())


def test_reconciliation_treats_malformed_approval_as_revoked():
    async def scenario():
        execution, access, jobs = gate()
        execution._seen.add((-100, 'encoder'))
        access.eligible.return_value = 'false'
        cleanup = AsyncMock()
        execution.cleanup_hook('encoder', cleanup)
        await execution.reconcile()
        cleanup.assert_awaited_once_with(-100)
        assert not execution._seen
        await jobs.shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value', [('enabled', 1), ('enabled', 'true'), ('disabled', None), ('disabled', 0)])
@pytest.mark.parametrize('chat', [-100, 22])
def test_optional_runtime_flags_require_known_boolean_values(field, value, chat):
    async def scenario():
        execution, access, jobs = gate()
        if field == 'enabled':
            execution.runtime.registry.is_enabled = lambda slug: value
        else:
            execution.runtime.wants_disabled = lambda slug: value
        handler = AsyncMock()
        await execution.wrap('encoder', handler)(None, message(chat))
        handler.assert_not_awaited()
        access.eligible.assert_not_awaited()
        await execution.wrap('moderation', handler)(None, message(chat))
        handler.assert_awaited_once()
        await jobs.shutdown()
    asyncio.run(scenario())


def test_repeated_plugin_cleanup_does_not_interrupt_child_cleanup():
    async def scenario():
        execution, _, jobs = gate()
        started, cleaning, release, cleaned, interrupted = (asyncio.Event() for _ in range(5))
        async def handler(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    interrupted.set()
                    raise
                cleaned.set()
        dispatcher = asyncio.create_task(execution.wrap('music', handler)(None, message()))
        await started.wait()
        first = asyncio.create_task(execution.cleanup(-100, 'music'))
        await cleaning.wait()
        second = asyncio.create_task(execution.cleanup(-100, 'music'))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second, dispatcher)
        assert cleaned.is_set() and not interrupted.is_set()
        assert not dispatcher.cancelled() and not execution._running
        await jobs.shutdown()
    asyncio.run(scenario())


def test_failed_plugin_cleanup_retains_scope_without_private_diagnostics(caplog):
    async def scenario():
        execution, _, jobs = gate()
        execution._seen.add((-100, 'encoder'))
        hook = AsyncMock(side_effect=RuntimeError('private-cleanup-token'))
        execution.cleanup_hook('encoder', hook)
        await execution.cleanup(-100, 'encoder')
        assert (-100, 'encoder') in execution._seen
        hook.side_effect = None
        await execution.cleanup(-100, 'encoder')
        assert (-100, 'encoder') not in execution._seen
        assert hook.await_count == 2
        await jobs.shutdown()
    asyncio.run(scenario())
    assert 'private-cleanup-token' not in caplog.text
    assert '#Errors' in caplog.text and 'RuntimeError' in caplog.text
    assert all(r.exc_info is None for r in caplog.records if r.name == 'agent.platform.execution')


def test_reconcile_watch_failure_retries_without_private_diagnostics(caplog):
    async def scenario():
        execution, _, jobs = gate()
        stop = asyncio.Event()
        calls = 0
        async def reconcile():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError('private-reconcile-token')
            stop.set()
        execution.reconcile = reconcile
        await execution.watch(stop, interval=0.001)
        assert calls == 2
        await jobs.shutdown()
    asyncio.run(scenario())
    assert 'private-reconcile-token' not in caplog.text
    assert '#Errors' in caplog.text and 'RuntimeError' in caplog.text
    assert all(r.exc_info is None for r in caplog.records if r.name == 'agent.platform.execution')
