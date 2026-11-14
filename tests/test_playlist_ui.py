"""Playlist metadata preview must not start playback or expose source fields."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_music_playlists import command_context
from test_music_controls import message
from test_player_card import FakeClient, STRANGER, OWNER
from agent.ui.tables import set_rich


def test_preview_is_authorized_read_only_and_rich(monkeypatch):
    async def scenario():
        _, queues, store, handlers = command_context(monkeypatch, [])
        store.inspect = AsyncMock(return_value={'titles': ['<unsafe>', 'second'], 'updated_at': None,
                                                 'source': 'SECRET_SOURCE'})
        denied = message('/playlistinfo mine', uid=STRANGER)
        await handlers['playlistinfo'](FakeClient(), denied)
        store.inspect.assert_not_awaited()
        request = message('/playlistinfo mine')
        request.id = 1
        request._client = SimpleNamespace(send_rich_message=AsyncMock())
        await handlers['playlistinfo'](FakeClient(), request)
        body = request._client.send_rich_message.await_args.kwargs['rich_text'].html
        assert '<table' in body and '<tg-emoji' in body
        assert '&lt;unsafe&gt;' in body and '<unsafe>' not in body
        assert 'second' in body and 'SECRET_SOURCE' not in body
        store.inspect.assert_awaited_once_with(-100, OWNER, 'mine')
        store.save.assert_not_awaited()
        store.load.assert_not_awaited()
        assert not queues.for_chat(-100).waiting
        assert queues.for_chat(-100).current.title == 'fresh'
    asyncio.run(scenario())


def test_playlist_library_empty_success_and_failure_panels(monkeypatch):
    async def scenario():
        _, _, store, handlers = command_context(monkeypatch, [])
        async def invoke(name, args=''):
            request = message('/' + name + (' ' + args if args else ''))
            request.id = 1
            request._client = SimpleNamespace(send_rich_message=AsyncMock())
            set_rich(True)
            await handlers[name](FakeClient(), request)
            return request._client.send_rich_message.await_args.kwargs['rich_text'].html
        body = await invoke('playlists')
        assert '0/10' in body and 'library is empty' in body
        store.list.return_value = [{'name': 'mine', 'count': 2}]
        assert '1/10' in await invoke('playlists')
        body = await invoke('saveplaylist', 'mine')
        assert 'PostgreSQL confirmed' in body
        body = await invoke('deleteplaylist', 'mine')
        assert 'Playlist deleted' in body and 'unchanged' in body
        store.delete.return_value = False
        assert 'Playlist not found' in await invoke('deleteplaylist', 'mine')
        store.delete.side_effect = RuntimeError('SECRET_DATABASE_URL')
        body = await invoke('deleteplaylist', 'mine')
        assert 'unconfirmed' in body and 'SECRET_DATABASE_URL' not in body
        body = await invoke('playlistinfo')
        assert 'Use /playlistinfo' in body
    asyncio.run(scenario())
