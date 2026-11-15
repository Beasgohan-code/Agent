"""Personal vault command boundaries, pagination and safe diagnostics."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import filestore
from test_plugins import make_ctx, FakeMessage, OWNER


def save(ctx, tmp_path, owner, name):
    path = tmp_path / 'payload'
    path.write_text(name)
    return ctx.storage.save_path(owner, path, name=name)


def test_removed_vault_commands_are_not_registered_and_data_is_preserved(tmp_path):
    ctx = make_ctx(tmp_path)
    stored = save(ctx, tmp_path, OWNER, 'keep.txt')
    manifest, commands = filestore.build(ctx)
    assert {'fsave', 'files', 'del'}.isdisjoint(manifest.commands)
    assert {'fsave', 'files', 'del'}.isdisjoint(commands)
    assert ctx.storage.get(stored.id) is not None
    assert ctx.storage.path_for(stored).is_file()


@pytest.mark.parametrize('command', ['/batch 0', '/batch 51', '/batch 1 extra', '/batch ' + '9'*5000,
                                     '/get id extra', '/check id extra'])
def test_invalid_args_refused_before_io(tmp_path, command):
    async def scenario():
        ctx = make_ctx(tmp_path)
        _, commands = filestore.build(ctx)
        request = FakeMessage(command)
        client = SimpleNamespace(get_messages=AsyncMock())
        await commands[command.split()[0][1:]](client, request)
        assert 'Usage' in request.replies[-1]
        client.get_messages.assert_not_awaited()
    asyncio.run(scenario())


def test_anonymous_vault_commands_refused(tmp_path):
    async def scenario():
        _, commands = filestore.build(make_ctx(tmp_path))
        for name, handler in commands.items():
            request = FakeMessage('/' + name)
            request.from_user = None
            await handler(None, request)
            assert 'personal Telegram user' in request.replies[-1]
    asyncio.run(scenario())


def test_vault_check_native_panel_preserves_record(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        stored = save(ctx, tmp_path, OWNER, 'entry.txt')
        stored.telegram_file_id = 'SECRET_TELEGRAM_REF'
        _, commands = filestore.build(ctx)
        for name in ['check']:
            request = FakeMessage(f'/{name} {stored.id}')
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands[name](None, request)
            body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
            assert '<table' in body and '<tg-emoji' in body
            assert 'SECRET_TELEGRAM_REF' not in body
            if name == 'check':
                assert 'recorded' in body and 'not a live availability check' in body
        assert ctx.storage.get(stored.id) is not None
    asyncio.run(scenario())
