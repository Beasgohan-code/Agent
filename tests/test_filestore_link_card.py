"""Native archive link controls use the issued bot-specific link."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from agent.modules.filestore.channel_links import build
from agent.modules import filestore
from test_archive_links import context, request, client
from test_filestore_clone_frontdoor import ctx


@pytest.mark.asyncio
async def test_link_ready_card_has_open_share_copy():
    value = context(NS(connected=True, _pool=object()))
    item = request()
    with patch('agent.modules.filestore.channel_links.create', AsyncMock(return_value='safe_token')):
        await build(value)['custom_batch'](client(), item)
    markup = item.reply.await_args.kwargs['reply_markup']
    buttons = [b for row in markup.inline_keyboard for b in row]
    url = 'https://t.me/MeikoBot?start=archive_safe_token'
    assert buttons[0].url == url
    assert 'share/url?' in buttons[1].url
    assert buttons[2].copy_text == url or getattr(buttons[2].copy_text, 'text', None) == url


@pytest.mark.asyncio
async def test_generation_configuration_change_never_calls_ticket_writer():
    value = context(NS(connected=True, _pool=object()))
    bot = client()
    async def changed(*args):
        value.settings.storage_channel = -200
        return [NS(id=i) for i in range(10, 13)]
    bot.get_messages.side_effect = changed
    with patch('agent.modules.filestore.channel_links.create', AsyncMock()) as create:
        await build(value)['custom_batch'](bot, request())
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_genlink_reply_ingests_without_second_upload():
    value = ctx()
    _, handlers = filestore.build(value)
    flow = value._filestore_conversation
    flow.receive = AsyncMock()
    original = request('file', mid=100)
    item = request('/genlink')
    item.reply_to_message = original
    await handlers['genlink'](None, item)
    flow.receive.assert_awaited_once_with(None, original)
