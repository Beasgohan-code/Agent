"""Single-message genlink copies new content only after archive authorization."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from pyrogram.enums import ChatMemberStatus
from agent.modules.filestore.conversation import ArchiveConversation
from test_archive_links import context, request, client


def flow():
    ctx = context(NS(connected=True, _pool=object()))
    generate = AsyncMock()
    return ctx, ArchiveConversation(ctx, generate), generate


@pytest.mark.asyncio
async def test_genlink_new_text_is_copied_once_then_linked_to_acknowledged_id():
    ctx, conversation, generate = flow()
    bot = client()
    await conversation.start(bot, request('/genlink'), 'genlink')
    incoming = request('My new post', mid=123)
    await conversation.receive(bot, incoming)
    bot.copy_message.assert_awaited_once_with(-100, 11, 123)
    assert bot.get_chat_member.await_count == 2
    assert generate.await_args.args[1].text == '/custom_batch 50 50'
    assert conversation.state is None
    await conversation.receive(bot, incoming)
    assert bot.copy_message.await_count == 1
    assert generate.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['foreign', 'not_admin', 'protected', 'db_down', 'copy_failure', 'copy_value_failure'])
async def test_genlink_ingest_refuses_before_copy_or_reports_unconfirmed(reason):
    ctx, conversation, generate = flow()
    bot = client()
    await conversation.start(bot, request('/genlink'), 'genlink')
    incoming = request('My post', uid=22 if reason == 'foreign' else 11, mid=123)
    if reason == 'not_admin':
        bot.get_chat_member.return_value = NS(status=ChatMemberStatus.MEMBER)
    if reason == 'protected':
        incoming.has_protected_content = True
    if reason == 'db_down':
        ctx.db.connected = False
    if reason in ('copy_failure', 'copy_value_failure'):
        bot.copy_message.side_effect = (ValueError if reason == 'copy_value_failure' else RuntimeError)('PRIVATE_TOKEN')
    await conversation.receive(bot, incoming)
    generate.assert_not_awaited()
    if reason not in ('copy_failure', 'copy_value_failure'):
        bot.copy_message.assert_not_awaited()
    else:
        assert 'unconfirmed' in str(incoming.reply.await_args.args[0]).lower()
        assert 'PRIVATE_TOKEN' not in str(incoming.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_configuration_change_during_copy_cannot_issue_link():
    ctx, conversation, generate = flow()
    bot = client()
    async def copy(*args):
        ctx.settings.storage_channel = -200
        return NS(id=50)
    bot.copy_message.side_effect = copy
    await conversation.start(bot, request('/genlink'), 'genlink')
    await conversation.receive(bot, request('New media caption', mid=123))
    generate.assert_not_awaited()
    assert conversation.state is None


@pytest.mark.asyncio
async def test_new_message_copy_creates_persisted_single_archive_link():
    import os
    import uuid
    from agent.platform.db import Database
    from agent.modules import filestore
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        pytest.skip('Database required')
    scope = 'ingest:' + uuid.uuid4().hex
    db = Database(os.environ['AGENT_TEST_DATABASE_URL'], scope=scope, required=True)
    assert await db.connect()
    try:
        ctx = context(db)
        ctx.settings.plugins, ctx.settings.db_scope = ('filestore',), 'clone:123456789'
        ctx.storage = NS()
        _, handlers = filestore.build(ctx)
        bot = client()
        bot.get_messages.return_value = [NS(id=50)]
        await handlers['genlink'](bot, request('/genlink'))
        sent = request('New post to share', mid=123)
        await ctx._filestore_conversation.receive(bot, sent)
        bot.copy_message.assert_awaited_once_with(-100, 11, 123)
        assert 'archive_' in str(sent.reply.await_args.args[0])
        async with db._pool.acquire() as conn:
            row = await conn.fetchrow('SELECT first_id,last_id FROM agent_archive_links WHERE tenant=$1', scope)
        assert tuple(row.values()) == (50, 50)
    finally:
        await db.close()
