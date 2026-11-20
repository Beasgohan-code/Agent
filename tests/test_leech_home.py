import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from agent.modules import leech
from agent.platform.actions import ActionRouter
from test_plugins import make_ctx
from test_archive_links import request


def test_leech_home_opens_without_network_or_job(tmp_path, monkeypatch):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.actions = ActionRouter()
        check = AsyncMock()
        monkeypatch.setattr(leech, "check_target", check)
        msg = request("/leech")
        await leech.build(ctx)[1]["leech"](None, msg)
        assert "Meiko · Leech" in str(msg.reply.await_args.args[0])
        buttons = msg.reply.await_args.kwargs["reply_markup"].inline_keyboard
        assert buttons[0][0].callback_data == "leech:help"
        check.assert_not_awaited()
        assert not ctx.jobs.active()
        query = NS(
            data="leech:help",
            from_user=msg.from_user,
            message=NS(chat=msg.chat, id=77, edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        assert await ctx.actions.dispatch(None, query)
        assert "/leech https://" in query.message.edit_text.await_args.kwargs["text"]
        query.data = "leech:backends"
        await ctx.actions.dispatch(None, query)
        assert (
            "Only direct public HTTP(S)"
            in query.message.edit_text.await_args.kwargs["text"]
        )
        query.data = "leech:invalid"
        await ctx.actions.dispatch(None, query)
        assert query.answer.await_args.kwargs["show_alert"]

    asyncio.run(scenario())


def test_leech_repeated_and_uneditable_screens_answer_clicks(tmp_path):
    from pyrogram.errors import MessageNotModified

    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.actions = ActionRouter()
        leech.build(ctx)
        msg = request("/leech")
        query = NS(
            data="leech:home",
            from_user=msg.from_user,
            message=NS(chat=msg.chat, id=77, edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        query.message.edit_text.side_effect = MessageNotModified()
        await ctx.actions.dispatch(None, query)
        query.answer.assert_awaited_once_with()
        query.answer.reset_mock()
        query.message.edit_text.side_effect = RuntimeError("private internal details")
        await ctx.actions.dispatch(None, query)
        assert query.answer.await_args.kwargs["show_alert"]
        assert "/leech" in query.answer.await_args.args[0]
        assert "private internal details" not in query.answer.await_args.args[0]

    asyncio.run(scenario())


def test_upload_settings_show_shared_state_only_in_private_chat(tmp_path):
    from agent.platform.attachments import CAPTION_KEY, THUMB_KEY

    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.actions = ActionRouter()
        leech.build(ctx)
        ctx.chats.put(11, CAPTION_KEY, "secret caption")
        ctx.chats.put(11, THUMB_KEY, "secret thumbnail id")
        query = NS(
            data="leech:uploads",
            from_user=NS(id=11),
            message=NS(chat=NS(id=11), id=77, edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        await ctx.actions.dispatch(None, query)
        text = query.message.edit_text.await_args.kwargs["text"]
        assert "configured" in text and "/set_thumb" in text
        assert "secret caption" not in text and "secret thumbnail id" not in text
        query.message.chat.id = -100
        query.message.edit_text.reset_mock()
        await ctx.actions.dispatch(None, query)
        query.message.edit_text.assert_not_awaited()
        assert query.answer.await_args.kwargs["show_alert"]
        query.message.chat.id = 11
        ctx.db = NS(connected=False)
        await ctx.actions.dispatch(None, query)
        assert "unavailable" in query.message.edit_text.await_args.kwargs["text"]
        assert "unknown" in query.message.edit_text.await_args.kwargs["text"]

    asyncio.run(scenario())
