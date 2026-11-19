"""Main-bot diagnostics and punctuation aliases have real guarded handlers."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock
from test_ops import ctx, FakeMessage, handlers, run
from agent.platform.commands import command_filter, command_name


def test_bstats_owner_private_and_live_rows(ctx):
    handler = handlers(ctx)['bstats']
    ctx.db = NS(connected=True, url='postgres://SECRET', _pending={1: 1})
    ctx.monitor = NS(snapshot=lambda: NS(uptime_seconds=125))
    message = FakeMessage('/bstats')
    message.chat.id = 11
    run(handler, message)
    text = str(message.replies[-1])
    assert 'Database' in text and '125' not in text  # formatted uptime
    assert '2m' in text and 'SECRET' not in text
    assert 'held' in text and 'Queued writes' in text


def test_bstats_no_snapshot_for_unauthorized_or_group(ctx):
    ctx.monitor = NS(snapshot=Mock(side_effect=AssertionError('must not read')))
    for uid, chat in ((22, 22), (11, -100)):
        message = FakeMessage('/bstats', uid=uid)
        message.chat.id = chat
        run(handlers(ctx)['bstats'], message)
        assert 'private' in message.replies[-1].lower() or 'owner' in message.replies[-1].lower()


def test_extended_prefixes_use_real_dispatch():
    async def scenario():
        for prefix in '#$%&':
            item = NS(text=prefix+'help@MeikoBot', caption=None)
            assert command_name(item.text) == 'help'
            assert await command_filter('help')(NS(me=NS(username='MeikoBot')), item)
            assert item.command == ['help']
            assert command_name(prefix+' help') is None
    asyncio.run(scenario())


def test_diagnostic_cards_do_not_name_storage_engine(ctx):
    from agent.platform.selection import SelectionError
    commands=handlers(ctx)
    ctx.db=NS(connected=True,url=None,_pending={},_docs={},error=None)
    ctx.lease=NS(backend='postgres',held=True,degraded=False)
    for command in ('bstats','db'):
        message=FakeMessage('/'+command)
        message.chat.id=11
        run(commands[command],message)
        text=str(message.replies[-1]).lower()
        assert 'postgres' not in text and 'psql' not in text
    assert 'postgres' not in str(SelectionError('missing_capabilities',fields=('postgresql',)))
