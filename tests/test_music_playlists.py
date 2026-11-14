"""Saved Music metadata: no local paths, no unbounded or cross-tenant lists."""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.platform import music_lists
from agent.platform.music_lists import MusicPlaylists, PlaylistError, validate_tracks
from agent.platform.db import Database
from agent.modules.music import playlists
from agent.modules.music.queue import QueueBook, Track
from agent.ui.theme import Theme
from test_music_controls import message
from test_player_card import FakeClient, OWNER, STRANGER


def track(title='track'):
    return {'title': title, 'source': 'https://media.example.test/' + title + '.mp3'}


@pytest.mark.parametrize('source', ['/tmp/private.session', 'file:///etc/passwd',
                                     'https://user:password@example.test/a',
                                     'https://example.test/a?token=secret',
                                     'https://example.test/a#token', 'http://localhost/a',
                                     'https://example.test:bad/a', 'https://example.test/a\nb'])
def test_playlist_rejects_non_stable_or_secret_sources(monkeypatch, source):
    validator = AsyncMock()
    monkeypatch.setattr(music_lists, 'check_target', validator)
    with pytest.raises(PlaylistError):
        asyncio.run(validate_tracks([{'title': 'track', 'source': source}]))
    validator.assert_not_awaited()


@pytest.mark.parametrize('tracks', [[], [track()] * 21, [None], [{'source': 123}],
                                    [{'source': 'https://example.test/a', 'title': ''}]])
def test_invalid_playlist_metadata_is_refused(tracks):
    with pytest.raises(PlaylistError):
        asyncio.run(validate_tracks(tracks))


def test_dns_validation_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(music_lists, 'check_target', AsyncMock(side_effect=RuntimeError('secret-url-value')))
    with pytest.raises(PlaylistError) as error:
        asyncio.run(validate_tracks([track()]))
    assert 'secret-url-value' not in str(error.value)


def test_database_is_required_and_identity_scope_is_checked():
    with pytest.raises(PlaylistError):
        asyncio.run(MusicPlaylists(None).list(-100, OWNER))
    service = MusicPlaylists(SimpleNamespace(connected=True, _pool=object(), scope='bot'))
    for group, user, name in [(100, OWNER, 'valid'), (-100, 0, 'valid'),
                              (-100, OWNER, "';drop table"), (-100, OWNER, 'UPPER')]:
        with pytest.raises(PlaylistError):
            service._scope(group, user, name)


def command_context(monkeypatch, rows):
    queues = QueueBook()
    queues.for_chat(-100).current = Track('fresh', 'https://example.test/fresh.mp3', OWNER)
    store = SimpleNamespace(save=AsyncMock(return_value=1), load=AsyncMock(return_value=rows),
                            list=AsyncMock(return_value=[]), delete=AsyncMock(return_value=True))
    monkeypatch.setattr(playlists, 'MusicPlaylists', lambda _: store)
    ctx = SimpleNamespace(db=object(), settings=SimpleNamespace(owner_id=OWNER), theme=Theme(),
                          voice=SimpleNamespace(playback=lambda _: object()))
    return ctx, queues, store, playlists.build_playlists(ctx, queues)


def test_playlist_loading_is_admin_only_and_all_or_nothing(monkeypatch):
    async def scenario():
        ctx, queues, store, commands = command_context(monkeypatch, [track()] * 2)
        denied = message('/playlist list', uid=STRANGER)
        await commands['playlist'](FakeClient(), denied)
        store.load.assert_not_awaited()
        queues.for_chat(-100).waiting = [Track('queued', 'source')] * 48
        await commands['playlist'](FakeClient(), message('/playlist list'))
        assert len(queues.for_chat(-100).waiting) == 48
        queues.for_chat(-100).waiting.clear()
        await commands['playlist'](FakeClient(), message('/playlist list'))
        assert len(queues.for_chat(-100).waiting) == 2
        assert queues.for_chat(-100).current.title == 'fresh'
        assert queues.for_chat(-100).waiting[0].requested_by == OWNER
        assert not queues.for_chat(-200).waiting
    asyncio.run(scenario())


def test_revocation_during_playlist_validation_blocks_admission(monkeypatch):
    async def scenario():
        ctx, queues, store, _ = command_context(monkeypatch, [track()])
        ctx.plugin_gate = SimpleNamespace(allowed=AsyncMock(return_value=False))
        commands = playlists.build_playlists(ctx, queues)
        request = message('/playlist list')
        await commands['playlist'](FakeClient(), request)
        assert not queues.for_chat(-100).waiting
        assert 'no longer active' in request.reply.await_args.args[0]
    asyncio.run(scenario())


def test_playlist_never_starts_playback_from_idle(monkeypatch):
    async def scenario():
        _, queues, store, commands = command_context(monkeypatch, [track()])
        queues.drop(-100)
        await commands['playlist'](FakeClient(), message('/playlist list'))
        store.load.assert_not_awaited()
        assert not queues.for_chat(-100).waiting
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get('AGENT_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_real_pg_playlist_quota_is_atomic_and_data_is_scoped(monkeypatch):
    async def scenario():
        monkeypatch.setattr(music_lists, 'check_target', AsyncMock())
        url = os.environ['AGENT_TEST_DATABASE_URL']
        tenant = 'music-lists-test:' + uuid.uuid4().hex
        db = Database(url, scope=tenant)
        other = Database(url, scope=tenant + ':other')
        try:
            assert await db.connect() and await other.connect()
            service = MusicPlaylists(db)
            results = await asyncio.gather(*(service.save(-100, OWNER, f'list{i}', [track()])
                                             for i in range(12)), return_exceptions=True)
            assert sum(isinstance(result, PlaylistError) for result in results) == 2
            assert len(await service.list(-100, OWNER)) == 10
            records = await service.list(-100, OWNER)
            name = records[0]['name']
            await service.save(-100, OWNER, name, [track('replacement')])
            assert (await service.load(-100, OWNER, name))[0]['title'] == 'replacement'
            preview = await service.inspect(-100, OWNER, name)
            assert preview['titles'] == ['replacement']
            assert 'source' not in str(preview) and 'https://' not in str(preview)
            for preview_service, group, user in [(service, -200, OWNER), (service, -100, STRANGER),
                                                   (MusicPlaylists(other), -100, OWNER)]:
                with pytest.raises(PlaylistError):
                    await preview_service.inspect(group, user, name)
            assert not await service.list(-200, OWNER)
            assert not await service.list(-100, STRANGER)
            assert not await MusicPlaylists(other).list(-100, OWNER)
            assert not await service.delete(-100, STRANGER, name)
            # Independent group/user limits, plus persistence across a reconnect.
            await service.save(-200, OWNER, 'same', [track()])
            await service.save(-100, STRANGER, 'same', [track()])
            await db.close()
            assert await db.connect()
            assert (await service.load(-100, OWNER, name))[0]['title'] == 'replacement'
            # Re-check DNS on load, not just when saving.
            monkeypatch.setattr(music_lists, 'check_target', AsyncMock(side_effect=RuntimeError('private target')))
            with pytest.raises(PlaylistError):
                await service.load(-100, OWNER, name)
            # Metadata preview works even when media DNS fails; no fetch/play implied.
            assert (await service.inspect(-100, OWNER, name))['titles'] == ['replacement']
            assert await service.delete(-100, OWNER, name)
            assert len(await service.list(-100, OWNER)) == 9
        finally:
            if db.connected:
                async with db._pool.acquire() as conn:
                    await conn.execute('DELETE FROM agent_music_playlists WHERE tenant=$1 OR tenant=$2', tenant, tenant + ':other')
            await db.close()
            await other.close()
    asyncio.run(scenario())


def test_saved_playlist_commands_are_capability_gated(tmp_path, monkeypatch):
    from test_player_card import build
    from agent.modules import music
    ctx, manifest, handlers = build(tmp_path, monkeypatch)
    assert len(handlers) == 26
    assert not set(playlists.COMMANDS).intersection(handlers)
    ctx.db = SimpleNamespace(connected=True, _pool=object(), scope='test')
    manifest, handlers = music.build(ctx)
    assert len(handlers) == 30
    assert set(manifest.commands) == set(handlers)
    assert set(playlists.COMMANDS).issubset(handlers)
