"""Transfer batch: owned pagination, safe details and strict options."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.modules import leech
from agent.platform.jobs import Job
from test_plugins import make_ctx, FakeMessage


@pytest.mark.parametrize('command', ['/leech', '/mirror a b', '/taskbackend extra', '/leechstats extra',
                                      '/taskstatus id extra', '/tasklist 0', '/tasklist ١'])
def test_bad_arguments_refused_without_network(tmp_path, command):
    async def scenario():
        ctx = make_ctx(tmp_path)
        request = FakeMessage(command)
        await leech.build(ctx)[1][command.split()[0][1:]](None, request)
        assert 'Usage' in request.replies[-1]
        assert not ctx.jobs.active()
    asyncio.run(scenario())


def test_transfer_history_and_status_hide_sensitive_fields(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        jobs = [Job(f'job{i:02d}', 'leech', 11, label='SECRET_URL', detail='SECRET_PATH', error='SECRET_ERROR') for i in range(23)]
        ctx.jobs = SimpleNamespace(for_owner=lambda uid: jobs if uid == 11 else [],
                                   get=lambda jid: next((job for job in jobs if job.id == jid), None))
        _, commands = leech.build(ctx)
        async def rich(text, name):
            request = FakeMessage(text)
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands[name](None, request)
            return request._client.send_rich_message.await_args.kwargs['rich_text'].html
        body = await rich('/tasklist 3', 'tasklist')
        assert '3/3' in body and 'job00' in body and 'job22' not in body and 'SECRET' not in body
        body = await rich('/taskstatus job00', 'taskstatus')
        assert 'SECRET' not in body and 'withheld' in body
        request = FakeMessage('/taskstatus job00', uid=99)
        await commands['taskstatus'](None, request)
        assert 'No task of yours' in request.replies[-1]
        body = await rich('/leechstats', 'leechstats')
        assert 'your tasks active' in body and 'across the bot' not in body
    asyncio.run(scenario())


def test_anonymous_transfer_commands_refused(tmp_path):
    async def scenario():
        _, commands = leech.build(make_ctx(tmp_path))
        for name, handler in commands.items():
            request = FakeMessage('/' + name)
            request.from_user = None
            await handler(None, request)
            assert 'personal Telegram' in request.replies[-1]
    asyncio.run(scenario())
