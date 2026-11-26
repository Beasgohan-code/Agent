"""Transfer batch: owned pagination, safe details and strict options."""
import asyncio

import pytest
from agent.modules import leech
from test_plugins import make_ctx, FakeMessage


@pytest.mark.parametrize('command', ['/leech', '/mirror a b'])
def test_bad_arguments_refused_without_network(tmp_path, command):
    async def scenario():
        ctx = make_ctx(tmp_path)
        request = FakeMessage(command)
        await leech.build(ctx)[1][command.split()[0][1:]](None, request)
        assert 'Usage' in request.replies[-1]
        assert not ctx.jobs.active()
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
