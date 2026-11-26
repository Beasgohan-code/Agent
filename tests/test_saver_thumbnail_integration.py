import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from agent.modules import leech
from agent.platform.attachments import attachment_kwargs, THUMB_KEY
from test_plugins import make_ctx
from test_archive_links import request


def test_thumbnail_commands_share_real_delivery_setting(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        commands = leech.build(ctx)[1]
        msg = request('/set_thumb')
        msg.reply_to_message = NS(photo=NS(file_id='telegram-photo-id'))
        await commands['set_thumb'](None, msg)
        assert attachment_kwargs(ctx.chats, 11, name='x', size='1 B')['thumb'] == 'telegram-photo-id'
        assert not ctx.chats.get(22, THUMB_KEY)
        client = NS(send_photo=AsyncMock())
        await commands['see_thumb'](client, request('/see_thumb'))
        client.send_photo.assert_awaited_once_with(11, 'telegram-photo-id', caption='Your personal upload thumbnail.')
        await commands['delete_thumb'](None, request('/delete_thumb'))
        assert 'thumb' not in attachment_kwargs(ctx.chats, 11, name='x', size='1 B')
    asyncio.run(scenario())


def test_thumbnail_validation_persistence_and_preview_failure(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        commands = leech.build(ctx)[1]
        invalid = request('/set_thumb')
        await commands['set_thumb'](None, invalid)
        assert not ctx.chats.get(11, THUMB_KEY)
        invalid.reply_to_message = NS(photo=NS(file_id='secret-reference'))
        invalid.chat.id = -100
        await commands['set_thumb'](None, invalid)
        assert not ctx.chats.get(-100, THUMB_KEY)
        invalid.chat.id = 11
        ctx.db = NS(connected=True, flush=AsyncMock(return_value=0))
        await commands['set_thumb'](None, invalid)
        assert 'not confirmed' in invalid.reply.await_args.args[0]
        view = request('/view_thumb')
        await commands['view_thumb'](NS(send_photo=AsyncMock(side_effect=RuntimeError('secret-reference'))), view)
        assert 'could not display' in view.reply.await_args.args[0]
        assert 'secret-reference' not in view.reply.await_args.args[0]
    asyncio.run(scenario())
