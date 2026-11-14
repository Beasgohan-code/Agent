"""Paged Music screens, native rich delivery and unchanged control semantics."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_music_controls import wire, invoke, message
from test_player_card import FakeClient, CHAT
from agent.ui.theme import Theme


def test_queue_pagination_reaches_every_position_without_mutating(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        for i in range(1, 24):
            await invoke(handlers, f'/play upcoming_{i:02d}_track')
        before = ctx.voice.play.await_count
        page1 = str((await invoke(handlers, '/queue')).reply.await_args.args[0])
        page2 = str((await invoke(handlers, '/q 2')).reply.await_args.args[0])
        page3 = str((await invoke(handlers, '/queue 3')).reply.await_args.args[0])
        assert 'Page <b>1/3</b>' in page1
        assert 'upcoming_10_track' in page1 and 'upcoming_11_track' not in page1
        assert 'upcoming_11_track' in page2 and 'upcoming_20_track' in page2
        assert 'upcoming_21_track' not in page2 and '/queue 3' in page2
        assert 'upcoming_23_track' in page3 and '/queue 2' in page3
        assert 'current' in page1 and 'current' in page2 and 'current' in page3
        assert ctx.voice.play.await_count == before
        # Page positions are real queue indices, not relative to each screen.
        await invoke(handlers, '/remove 21')
        page3 = str((await invoke(handlers, '/queue 3')).reply.await_args.args[0])
        assert 'upcoming_21_track' not in page3 and 'upcoming_22_track' in page3
        other = str((await invoke(handlers, '/queue', chat=CHAT - 1)).reply.await_args.args[0])
        assert 'Nothing queued' in other and 'upcoming_' not in other
    asyncio.run(scenario())


@pytest.mark.parametrize('arg', ['0', '-1', 'abc', '2 3', '999', '١', '1.5'])
def test_bad_pages_do_not_touch_voice(tmp_path, monkeypatch, arg):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        response = await invoke(handlers, '/queue ' + arg)
        assert 'Use /queue' in response.reply.await_args.args[0]
        ctx.voice.play.assert_not_awaited()
    asyncio.run(scenario())


def test_stale_page_returns_range(tmp_path, monkeypatch):
    async def scenario():
        _, _, handlers = wire(tmp_path, monkeypatch)
        response = await invoke(handlers, '/queue 2')
        assert 'from 1 to 1' in response.reply.await_args.args[0]
    asyncio.run(scenario())


def test_rich_queue_player_volume_and_feedback(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play <unsafe>')
        await invoke(handlers, '/play next')
        await invoke(handlers, '/loop all')
        from agent.ui.tables import set_rich
        set_rich(True)
        client = SimpleNamespace(send_rich_message=AsyncMock())
        async def rich_request(text):
            request = message(text)
            request.id = 42
            request._client = client
            await handlers[text.split()[0][1:]](FakeClient(), request)
            request.reply.assert_not_awaited()
            return client.send_rich_message.await_args.kwargs['rich_text'].html
        queue = await rich_request('/queue')
        assert '<table' in queue and '<tg-emoji' in queue
        assert '&lt;unsafe&gt;' in queue and '<unsafe>' not in queue
        player = await rich_request('/nowplaying')
        assert 'Upcoming' in player and 'Repeat' in player and 'all' in player
        assert 'not set this session' in player
        update = await rich_request('/volume 140')
        assert 'Music updated' in update and '140%' in update
        volume = await rich_request('/volume')
        assert '<table' in volume and '140%' in volume
        assert 'acknowledged' in volume
        player = await rich_request('/nowplaying')
        assert '140% acknowledged' in player
    asyncio.run(scenario())


def test_plain_theme_and_validation_feedback(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        ctx.theme = Theme({})
        response = await invoke(handlers, '/loop invalid')
        body = str(response.reply.await_args.args[0])
        assert 'Check this action' in body and '<tg-emoji' not in body
        response = await invoke(handlers, '/history unexpected')
        assert 'without arguments' in response.reply.await_args.args[0]
    asyncio.run(scenario())
