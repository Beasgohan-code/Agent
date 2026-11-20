"""Custom batches must contain exactly selected posts, not an archive range."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules.filestore.conversation import ArchiveConversation
from test_archive_links import context, request, client
from test_filestore_clone_frontdoor import ctx
from agent.modules import filestore


@pytest.mark.asyncio
async def test_custom_selection_preserves_explicit_order_and_excludes_gaps():
    generate = AsyncMock()
    flow = ArchiveConversation(context(), generate)
    await flow.start(None, request('/custom_batch'), 'custom_selection')
    for mid in (12, 10):
        item = request('', mid=mid)
        item.forward_from_chat, item.forward_from_message_id = NS(id=-100), mid
        await flow.receive(None, item)
    await flow.receive(None, request('/done'))
    assert generate.await_args.args[1].text == '/custom_batch ids 12 10'
    assert flow.state is None


@pytest.mark.asyncio
async def test_custom_selection_new_uploads_copy_once_each_then_finish():
    value = context(NS(connected=True, _pool=object()))
    generate = AsyncMock()
    flow = ArchiveConversation(value, generate)
    bot = client()
    bot.copy_message.side_effect = [NS(id=50), NS(id=52)]
    await flow.start(bot, request('/custom_batch'), 'custom_selection')
    first = request('first post', mid=111)
    await flow.receive(bot, first)
    await flow.receive(bot, first)  # duplicate Telegram input is not another copy
    await flow.receive(bot, request('second post', mid=112))
    assert bot.copy_message.await_count == 2
    generate.assert_not_awaited()
    await flow.receive(bot, request('/done'))
    assert generate.await_args.args[1].text == '/custom_batch ids 50 52'
    await flow.receive(bot, request('/done'))
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_clone_entrypoint_uses_selection_but_controller_keeps_range():
    for scope, mode in (('clone:111111111', 'custom_selection'), ('main', 'custom_batch')):
        value = ctx(scope=scope)
        _, handlers = filestore.build(value)
        await handlers['custom_batch'](None, request('/custom_batch'))
        assert value._filestore_conversation.state['mode'] == mode


@pytest.mark.asyncio
async def test_selection_limit_and_failed_copy_never_publish_partial_batch():
    value = context(NS(connected=True, _pool=object()))
    generate = AsyncMock()
    flow = ArchiveConversation(value, generate)
    bot = client()
    await flow.start(bot, request('/custom_batch'), 'custom_selection')
    flow.state['ids'] = list(range(1, 51))
    await flow.receive(bot, request('extra upload', mid=999))
    bot.copy_message.assert_not_awaited()
    assert len(flow.state['ids']) == 50
    flow.state['ids'] = [10]
    bot.copy_message.side_effect = RuntimeError('PRIVATE_TOKEN')
    await flow.receive(bot, request('failed upload', mid=998))
    assert flow.state is None
    await flow.receive(bot, request('/done'))
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_selection_persists_only_exact_ids_in_postgresql():
    import os
    import uuid
    from agent.platform.db import Database
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    scope = 'custom-selection:' + uuid.uuid4().hex
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True)
    assert await db.connect()
    try:
        value = ctx()
        value.db = db
        _, handlers = filestore.build(value)
        bot = client()
        bot.get_messages.return_value = [NS(id=12), NS(id=10)]
        await handlers['custom_batch'](bot, request('/custom_batch'))
        for mid in (12, 10):
            item = request('', mid=mid)
            item.forward_from_chat, item.forward_from_message_id = NS(id=-100), mid
            await value._filestore_conversation.receive(bot, item)
        done = request('/done')
        await value._filestore_conversation.receive(bot, done)
        assert 'archive_' in str(done.reply.await_args.args[0])
        bot.get_messages.assert_awaited_once_with(-100, [12, 10])
        async with db._pool.acquire() as conn:
            ids = await conn.fetchval('SELECT message_ids FROM agent_archive_links WHERE tenant=$1', scope)
        assert ids == [12, 10] and 11 not in ids
        bot.copy_message.assert_not_awaited()
    finally:
        await db.close()
