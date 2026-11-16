"""Build actual tenant bots and exercise their actual plugin execution gates."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from agent.modules.clone.manager import _default_factory
from agent.modules.clone.store import Clone
from agent.platform.policy import GROUP_CORE
from test_clone import build, TOKEN_A, TOKEN_B, MEMBER


@pytest.mark.parametrize(
    "slug",
    [
        "filestore",
        "encoder",
        "linkshare",
        "leech",
        "postmaker",
        "moderation",
        "ai_agent",
    ],
)
def test_real_clone_build_registers_selected_plugin_and_mandatory_core(tmp_path, slug):
    ctx, _, _ = build(tmp_path)
    record = Clone(
        bot_id=111111111,
        owner_id=MEMBER,
        token=TOKEN_A,
        selected_plugins=(slug,),
        profile="tiny",
        ai_api_key="sk-clone_provider_key_1234567890" if slug == "ai_agent" else None,
        ai_model="clone-model" if slug == "ai_agent" else None,
        storage_channel=-100111,
    )
    settings = ctx.clones.settings_for(record)
    worker = _default_factory(settings)
    worker.build()  # Actual AgentBot, registry, commands, watchers and plugin gates.
    manifests = {manifest.slug: manifest for manifest in worker.registry.manifests()}
    assert slug in manifests
    assert manifests[slug].commands
    assert worker.registry.is_enabled(slug)
    assert set(GROUP_CORE) <= set(manifests)
    assert "clone" not in manifests
    assert worker.settings.owner_id == MEMBER
    assert worker.settings.db_scope == "clone:111111111"
    assert worker.settings.bot_token == TOKEN_A
    assert worker.settings.storage_channel == -100111
    assert worker.settings.log_channel is None
    assert worker.settings.session_string is None


def test_real_clone_runtime_switch_and_group_approval_do_not_cross_tenants(tmp_path):
    async def scenario():
        ctx, _, _ = build(tmp_path)
        a = Clone(
            bot_id=111111111,
            owner_id=MEMBER,
            token=TOKEN_A,
            selected_plugins=("encoder",),
        )
        b = replace(a, bot_id=222222222, token=TOKEN_B, owner_id=33)
        workers = [
            _default_factory(ctx.clones.settings_for(record)) for record in (a, b)
        ]
        for worker in workers:
            worker.build()
        first, second = workers
        assert first.plugin_access is not second.plugin_access
        assert first.runtime is not second.runtime
        assert first.modules.storage is not second.modules.storage
        first.runtime.registry.disable("encoder")
        assert not first.registry.is_enabled("encoder")
        assert second.registry.is_enabled("encoder")
        handler = AsyncMock()
        update = NS(chat=NS(id=33), reply=AsyncMock())
        await second.plugin_gate.wrap("encoder", handler)(None, update)
        handler.assert_awaited_once()
        handler.reset_mock()
        # A group without Owner approval/activation cannot execute it.
        group = NS(chat=NS(id=-100123), reply=AsyncMock())
        await second.plugin_gate.wrap("encoder", handler)(None, group)
        handler.assert_not_awaited()
        assert first.settings.data_dir != second.settings.data_dir
        assert first.settings.link_secret != second.settings.link_secret

    asyncio.run(scenario())


def test_pg_real_workers_boot_persist_isolated_state_and_release_leases(tmp_path):
    import os
    import secrets
    from agent.modules.clone.manager import CloneManager, CloneError

    if not os.environ.get("AGENT_TEST_DATABASE_URL"):
        pytest.skip("PostgreSQL required")

    async def scenario():
        ctx, _, _ = build(tmp_path)
        manager = ctx.clones
        ctx.premium.ids.add(MEMBER + 1)
        manager._settings = replace(
            ctx.settings,
            database_url=os.environ["AGENT_TEST_DATABASE_URL"],
            sync_commands=False,
        )
        made = []

        def factory(settings):
            worker = _default_factory(settings)
            real_build = worker.build

            def offline_build():
                client = real_build()
                client.start = AsyncMock()
                client.stop = AsyncMock()
                client.get_me = AsyncMock(
                    return_value=NS(
                        id=settings.bot_id, username=f"bot{settings.bot_id}"
                    )
                )
                client.set_chat_menu_button = AsyncMock()
                client.send_message = AsyncMock(return_value=NS(id=1))
                return client

            worker.build = offline_build
            made.append(worker)
            return worker

        manager._factory = factory
        records = []
        for index, slug in enumerate(("filestore", "encoder")):
            bot_id = 700000000 + secrets.randbelow(90000000)
            record = Clone(
                bot_id=bot_id,
                owner_id=MEMBER + index,
                token=f"{bot_id}:test-secret",
                selected_plugins=(slug,),
            )
            records.append(manager._store.add(record))
        try:
            for record in records:
                await manager.start(record)
            first, second = made
            assert first.lease.held and second.lease.held
            assert first.database.scope != second.database.scope
            first.database.save("worker-integration", {"owner": records[0].owner_id})
            second.database.save("worker-integration", {"owner": records[1].owner_id})
            await first.database.flush()
            await second.database.flush()
            assert first.database.get("worker-integration") != second.database.get(
                "worker-integration"
            )
            contender = CloneManager(manager._settings, manager._store, factory=factory)
            with pytest.raises(CloneError):
                await contender.start(records[0])
            assert first.lease.held
            for record in records:
                await manager.stop(record.bot_id)
            assert all(
                not worker.database.connected and not worker.lease.held
                for worker in made
            )
            # Rebuild the actual worker and hydrate its original tenant data.
            await manager.start(records[0])
            assert made[-1].database.get("worker-integration") == {
                "owner": records[0].owner_id
            }
        finally:
            await manager.stop_all()
            # Disposable test DB only: remove this test's worker document namespaces.
            from agent.platform.db import Database

            db = Database(
                os.environ["AGENT_TEST_DATABASE_URL"],
                scope="integration-cleanup",
                required=True,
            )
            try:
                assert await db.connect()
                async with db._pool.acquire() as conn:
                    for record in records:
                        await conn.execute(
                            "DELETE FROM agent_documents WHERE name LIKE $1",
                            f"clone:{record.bot_id}:%",
                        )
            finally:
                await db.close()

    asyncio.run(scenario())


def test_real_file_suite_worker_loads_all_reviewed_tools(tmp_path):
    from agent.modules.clone.catalog import FILE_SUITE

    ctx, _, _ = build(tmp_path)
    record = Clone(
        bot_id=111111111,
        owner_id=MEMBER,
        token=TOKEN_A,
        selected_plugins=FILE_SUITE,
        storage_channel=-100123,
    )
    worker = _default_factory(ctx.clones.settings_for(record))
    worker.build()
    for slug in FILE_SUITE:
        assert worker.registry.is_enabled(slug)
    assert worker.deeplinks._routes.get("archive") is not None
    assert worker.deeplinks._routes.get("link") is not None
    assert "clone" not in {manifest.slug for manifest in worker.registry.manifests()}


def test_real_full_suite_worker_registers_all_features_without_parent_secrets(tmp_path, monkeypatch):
    from agent.modules.clone.catalog import FULL_SUITE
    from agent.modules.clone import assistant
    import agent.bot as bot_module
    from agent.modules import music
    monkeypatch.setattr(bot_module, 'capability', lambda session: (True, ''))
    monkeypatch.setattr(music, 'capability', lambda session: (True, ''))
    monkeypatch.setattr('agent.platform.voice.capability', lambda session: (True, ''))
    monkeypatch.setattr(assistant, 'validate_session', lambda session: None)
    ctx, _, _ = build(tmp_path)
    ctx.clones._settings = replace(ctx.settings, database_url='postgresql://test',
        ai_api_key='parent-secret', ai_model='parent-model', session_string='parent-session')
    record = Clone(bot_id=111111111, owner_id=MEMBER, token=TOKEN_A,
        selected_plugins=FULL_SUITE, storage_channel=-100123,
        assistant_session='own-assistant', ai_api_key='sk-own_provider_key_1234567890', ai_model='own-model')
    settings = ctx.clones.settings_for(record)
    worker = _default_factory(settings)
    worker.build()
    manifests = {manifest.slug: manifest for manifest in worker.registry.manifests()}
    for slug in FULL_SUITE:
        assert slug in manifests and manifests[slug].commands
        assert worker.registry.is_enabled(slug)
    assert set(GROUP_CORE) <= set(manifests)
    assert 'clone' not in manifests
    assert worker.settings.session_string == 'own-assistant'
    assert worker.settings.ai_api_key == 'sk-own_provider_key_1234567890'
    assert worker.settings.ai_model == 'own-model'
    assert worker.settings.db_scope == 'clone:111111111'
    assert worker.deeplinks._routes.get('archive') is not None
    assert worker.deeplinks._routes.get('link') is not None


def test_full_suite_worker_postgres_lifecycle_and_restart(tmp_path, monkeypatch):
    import os
    import secrets
    import agent.bot as bot_module
    from agent.modules import music
    from agent.modules.clone import assistant
    from agent.modules.clone.catalog import FULL_SUITE
    from agent.platform.db import Database

    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('PostgreSQL required')
    monkeypatch.setattr(assistant, 'validate_session', lambda session: None)
    monkeypatch.setattr(bot_module, 'capability', lambda session: (True, ''))
    monkeypatch.setattr(music, 'capability', lambda session: (True, ''))
    monkeypatch.setattr('agent.platform.voice.capability', lambda session: (True, ''))

    async def scenario():
        ctx, _, _ = build(tmp_path)
        manager = ctx.clones
        manager._settings = replace(ctx.settings,
            database_url=os.environ['AGENT_TEST_DATABASE_URL'], sync_commands=False)
        made = []
        def factory(settings):
            worker = _default_factory(settings)
            original = worker.build
            async def connect_voice():
                worker.voice._connected = True  # Offline transport stub, not live voice verification.
            worker.voice.start = AsyncMock(side_effect=connect_voice)
            def offline_build():
                client = original()
                client.start = AsyncMock()
                client.stop = AsyncMock()
                client.get_me = AsyncMock(return_value=NS(id=settings.bot_id, username='fullsuite'))
                client.set_chat_menu_button = AsyncMock()
                client.send_message = AsyncMock(return_value=NS(id=1))
                return client
            worker.build = offline_build
            made.append(worker)
            return worker
        manager._factory = factory
        bot_id = 800000000 + secrets.randbelow(90000000)
        record = Clone(bot_id=bot_id, owner_id=MEMBER, token=f'{bot_id}:private-test-token',
            selected_plugins=FULL_SUITE, storage_channel=-100123,
            assistant_session='own-assistant', ai_api_key='sk-own_provider_key_1234567890', ai_model='own-model')
        manager._store.add(record)
        try:
            await manager.start(record)
            first = made[-1]
            assert first.database.connected and first.lease.held
            assert all(first.registry.is_enabled(slug) for slug in FULL_SUITE)
            first.database.save('fullsuite-state', {'owner': MEMBER})
            assert await first.database.flush() > 0
            await manager.restart(record)
            assert not first.database.connected and not first.lease.held
            second = made[-1]
            assert second is not first
            assert second.database.get('fullsuite-state') == {'owner': MEMBER}
            assert second.settings.ai_api_key == 'sk-own_provider_key_1234567890'
            assert second.settings.session_string == 'own-assistant'
            assert second.voice.connected and manager.is_running(bot_id)
        finally:
            await manager.stop_all()
            db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope='fullsuite-test-cleanup', required=True)
            try:
                assert await db.connect()
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_documents WHERE name LIKE $1', f'clone:{bot_id}:%')
            finally:
                await db.close()
    asyncio.run(scenario())
