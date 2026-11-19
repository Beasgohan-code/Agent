"""FileStore-only clones get archive /genlink without controller/linkshare collisions."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules import filestore, linkshare
from agent.modules.filestore.conversation import ArchiveConversation
from agent.platform.manifest import PluginRegistry
from agent.ui.theme import Theme
from agent.ui.workers import commands, overview
from test_archive_links import context, request


def ctx(scope='clone:111111111', plugins=('filestore',)):
    value = context()
    value.settings.db_scope, value.settings.plugins = scope, plugins
    value.storage = NS()
    return value


def test_clone_variant_commands_and_controller_compatibility():
    context = ctx()
    manifest, handlers = filestore.build(context)
    assert 'genlink' in manifest.commands and 'get' not in manifest.commands
    assert set(manifest.commands) == set(handlers)
    registry = PluginRegistry()
    registry.register(manifest, handlers)
    active = set(registry.active_commands())
    assert 'genlink' in commands('filestore', active)
    home = overview(None, Theme(worker_plugins=('filestore',)), active=active)
    assert '/genlink' in home.rich_text and '/get' not in home.rich_text
    for value in (ctx(scope='main'), ctx(plugins=('filestore', 'linkshare'))):
        original, _ = filestore.build(value)
        assert 'get' in original.commands and 'genlink' not in original.commands
    assert 'genlink' in linkshare.MANIFEST.commands


@pytest.mark.asyncio
async def test_single_archive_prompt_finishes_once_and_checks_identity():
    generate = AsyncMock()
    flow = ArchiveConversation(context(), generate)
    await flow.start(None, request('/genlink'), 'genlink')
    assert flow.state['mode'] == 'genlink'
    wrong = request('', 22)
    wrong.forward_from_chat, wrong.forward_from_message_id = NS(id=-100), 10
    await flow.receive(None, wrong)
    generate.assert_not_awaited()
    item = request('')
    item.forward_from_chat, item.forward_from_message_id = NS(id=-100), 10
    await flow.receive(None, item)
    assert generate.await_args.args[1].text == '/custom_batch 10 10'
    assert flow.state is None
    await flow.receive(None, item)
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_clone_genlink_is_private_owner_only_and_bounded():
    value = ctx()
    _, handlers = filestore.build(value)
    for message in (request('/genlink', 22), request('/genlink 1 2')):
        await handlers['genlink'](None, message)
        assert value._filestore_conversation.state is None
    start = request('/genlink')
    await handlers['genlink'](None, start)
    assert 'archive' in str(start.reply.await_args.args[0]).lower()
    await value._filestore_conversation.receive(None, request('/cancel'))
    assert value._filestore_conversation.state is None


@pytest.mark.asyncio
async def test_clone_genlink_creates_real_scoped_archive_ticket():
    import os
    import uuid
    from agent.platform.db import Database
    from test_archive_links import client
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    scope = 'fs-clone:' + uuid.uuid4().hex
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True)
    assert await db.connect()
    try:
        value = ctx()
        value.db = db
        _, handlers = filestore.build(value)
        bot = client()
        bot.get_messages.return_value = [NS(id=10)]
        await handlers['genlink'](bot, request('/genlink'))
        item = request('')
        item.forward_from_chat, item.forward_from_message_id = NS(id=-100), 10
        await value._filestore_conversation.receive(bot, item)
        assert 'archive_' in str(item.reply.await_args.args[0])
        async with db._pool.acquire() as conn:
            row = await conn.fetchrow('SELECT first_id,last_id FROM agent_archive_links WHERE tenant=$1', scope)
        assert tuple(row.values()) == (10, 10)
        assert bot.get_chat_member.await_count == 2
        assert value._filestore_conversation.state is None
    finally:
        await db.close()
