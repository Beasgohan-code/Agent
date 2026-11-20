import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from agent.modules import renamer
from agent.platform.attachments import CAPTION_KEY, THUMB_KEY
from test_plugins import make_ctx
from test_archive_links import request


def test_legacy_attachment_commands_confirm_database_and_bound_unicode(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        commands = renamer.build(ctx)[1]
        too_long = request('/setcaption ' + '😀' * 513)
        await commands['setcaption'](None, too_long)
        assert not ctx.chats.get(11, CAPTION_KEY)
        assert 'UTF-16' in too_long.reply.await_args.args[0]
        ctx.db = NS(connected=False, flush=AsyncMock())
        offline = request('/setcaption blocked')
        await commands['setcaption'](None, offline)
        assert not ctx.chats.get(11, CAPTION_KEY)
        assert 'unavailable' in offline.reply.await_args.args[0]
        ctx.db.connected = True
        ctx.db.flush.return_value = 0
        thumb = request('/setthumb')
        thumb.reply_to_message = NS(photo=NS(file_id='photo-reference'))
        await commands['setthumb'](None, thumb)
        assert 'not confirmed' in thumb.reply.await_args.args[0]
        ctx.db.flush.return_value = 1
        saved = request('/setcaption {filename}')
        await commands['setcaption'](None, saved)
        assert 'Caption saved' in saved.reply.await_args.args[0]
        removed = request('/delthumb')
        await commands['delthumb'](None, removed)
        assert not ctx.chats.get(11, THUMB_KEY)
        assert 'cleared' in removed.reply.await_args.args[0]
    asyncio.run(scenario())
