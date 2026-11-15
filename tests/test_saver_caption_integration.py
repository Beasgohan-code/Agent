import asyncio
from agent.modules import leech
from agent.platform.attachments import CAPTION_KEY, attachment_kwargs
from test_plugins import make_ctx
from test_archive_links import request


def test_saver_commands_feed_existing_attachment_pipeline(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        commands = leech.build(ctx)[1]
        msg = request("/set_caption File: {filename} | {size}")
        await commands["set_caption"](None, msg)
        assert (
            attachment_kwargs(ctx.chats, 11, name="hello.mkv", size="5 MB")["caption"]
            == "File: hello.mkv | 5 MB"
        )
        assert not ctx.chats.get(22, CAPTION_KEY)
        view = request("/see_caption")
        await commands["see_caption"](None, view)
        assert "filename" in view.reply.await_args.args[0]
        await commands["del_caption"](None, request("/del_caption"))
        assert "caption" not in attachment_kwargs(ctx.chats, 11, name="x", size="1 B")

    asyncio.run(scenario())


def test_saver_caption_rejects_groups_and_oversize_unicode(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        commands = leech.build(ctx)[1]
        group = request("/set_caption bad")
        group.chat.id = -100
        await commands["set_caption"](None, group)
        assert not ctx.chats.get(-100, CAPTION_KEY)
        await commands["set_caption"](None, request("/set_caption " + "😀" * 513))
        assert not ctx.chats.get(11, CAPTION_KEY)

    asyncio.run(scenario())


def test_saver_caption_does_not_claim_failed_database_flush_was_saved(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.db = SimpleNamespace(connected=True, flush=AsyncMock(return_value=0))
        msg = request("/set_caption {filename}")
        await leech.build(ctx)[1]["set_caption"](None, msg)
        assert "not confirmed" in msg.reply.await_args.args[0]

    asyncio.run(scenario())
