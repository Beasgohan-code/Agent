import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from agent.modules.renamer.rules import build_rules
from agent.platform.media_rules import DELETE_KEY, transform
from test_plugins import make_ctx
from test_archive_links import request


def test_rules_refuse_offline_storage_before_cache_mutation(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.db = NS(connected=False, flush=AsyncMock())
        msg = request('/set_del_word unwanted')
        await build_rules(ctx)['set_del_word'](None, msg)
        assert not ctx.chats.get(11, DELETE_KEY)
        assert 'unavailable' in msg.reply.await_args.args[0]
        ctx.db.flush.assert_not_awaited()
    asyncio.run(scenario())


def test_rules_confirm_flush_and_report_unconfirmed_writes(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.db = NS(connected=True, flush=AsyncMock(return_value=1))
        commands = build_rules(ctx)
        first = request('/set_repl_word old new')
        await commands['set_repl_word'](None, first)
        ctx.db.flush.assert_awaited_once()
        assert transform(ctx.chats, 11, 'old.mkv') == 'new.mkv'
        assert 'Media rules updated' in first.reply.await_args.args[0]
        ctx.db.flush.return_value = 0
        failed = request('/set_del_word unwanted')
        await commands['set_del_word'](None, failed)
        assert 'not confirmed' in failed.reply.await_args.args[0]
        assert 'Media rules updated' not in failed.reply.await_args.args[0]
        ctx.db.flush.side_effect = RuntimeError('private connection secret')
        failure = request('/rem_repl_word old')
        await commands['rem_repl_word'](None, failure)
        assert 'not confirmed' in failure.reply.await_args.args[0]
        assert 'private connection secret' not in failure.reply.await_args.args[0]
    asyncio.run(scenario())
