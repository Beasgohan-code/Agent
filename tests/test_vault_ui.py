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


def test_pagination_exposes_all_owned_files_not_other_users(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        for i in range(23):
            stored = save(ctx, tmp_path, OWNER, f'file_{i:02d}.txt')
            stored.created_at = i + 1
        save(ctx, tmp_path, 99, 'OTHER_PRIVATE.txt')
        _, commands = filestore.build(ctx)
        pages = []
        for page in range(1, 4):
            request = FakeMessage(f'/files {page}')
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands['files'](None, request)
            pages.append(request._client.send_rich_message.await_args.kwargs['rich_text'].html)
        assert 'Page <b>1/3</b>' in pages[0] and '/files 2' in pages[0]
        assert 'file_22.txt' in pages[0] and 'file_12.txt' not in pages[0]
        assert 'file_12.txt' in pages[1] and 'file_00.txt' in pages[2]
        assert all('OTHER_PRIVATE' not in body for body in pages)
        request = FakeMessage('/files 4')
        await commands['files'](None, request)
        assert 'from 1 to 3' in request.replies[-1]
    asyncio.run(scenario())


@pytest.mark.parametrize('command', ['/files 0', '/files -1', '/files ١', '/files 1 extra',
                                     '/batch 0', '/batch 51', '/batch 1 extra', '/batch ' + '9'*5000,
                                     '/get id extra', '/del id extra', '/check id extra'])
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


def test_vault_check_and_delete_native_panels(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        stored = save(ctx, tmp_path, OWNER, 'entry.txt')
        stored.telegram_file_id = 'SECRET_TELEGRAM_REF'
        _, commands = filestore.build(ctx)
        for name in ['check', 'del']:
            request = FakeMessage(f'/{name} {stored.id}')
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            await commands[name](None, request)
            body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
            assert '<table' in body and '<tg-emoji' in body
            assert 'SECRET_TELEGRAM_REF' not in body
            if name == 'check':
                assert 'recorded' in body and 'not a live availability check' in body
            else:
                assert 'not remotely erased' in body
        assert ctx.storage.get(stored.id) is None
    asyncio.run(scenario())
