"""Playlist metadata preview must not start playback or expose source fields."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_music_playlists import command_context
from test_music_controls import message
from test_player_card import FakeClient
from agent.ui.tables import set_rich


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
    asyncio.run(scenario())
