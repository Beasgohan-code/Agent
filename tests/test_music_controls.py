"""Queue operations and acknowledgements, without Telegram or external media."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_player_card import build, FakeClient, CHAT, OWNER, STRANGER
from agent.modules import music
from agent.modules.music.queue import ChatQueue, Track
from agent.platform.voice import Playback, VoiceUnavailable


def message(text, uid=OWNER, chat=CHAT):
    from pyrogram.enums import ChatType
    return SimpleNamespace(text=text, chat=SimpleNamespace(id=chat, type=ChatType.SUPERGROUP),
                           from_user=SimpleNamespace(id=uid), reply=AsyncMock())


def wire(tmp_path, monkeypatch):
    ctx, manifest, handlers = build(tmp_path, monkeypatch)
    async def resolve(request, arg):
        return 'https://example.test/' + arg, arg
    monkeypatch.setattr(music, 'resolve', resolve)
    async def play(chat, source, *, title, requested_by):
        ctx.voice.playbacks[chat] = Playback(title, source, requested_by=requested_by)
    ctx.voice.play = AsyncMock(side_effect=play)
    ctx.voice.volume = AsyncMock()
    return ctx, manifest, handlers


async def invoke(handlers, text, **kwargs):
    request = message(text, **kwargs)
    await handlers[text.split()[0][1:].split('@')[0]](FakeClient(), request)
    return request


async def contents(handlers):
    request = await invoke(handlers, '/queue')
    return str(request.reply.await_args.args[0])


def test_all_new_music_commands_are_declared_and_group_scoped(tmp_path, monkeypatch):
    ctx, manifest, handlers = wire(tmp_path, monkeypatch)
    assert set(manifest.commands) == set(handlers)
    assert len(handlers) == 25
    assert manifest.scope == 'group'


def test_queue_reorder_clear_and_admin_permissions(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        for title in ['current', 'first', 'second', 'third']:
            await invoke(handlers, '/play ' + title)
        denied = await invoke(handlers, '/clearqueue', uid=STRANGER)
        assert 'administrators' in denied.reply.await_args.args[0]
        await invoke(handlers, '/move 3 1')
        body = await contents(handlers)
        assert body.index('third') < body.index('first') < body.index('second')
        await invoke(handlers, '/remove 2')
        assert 'first' not in await contents(handlers)
        await invoke(handlers, '/clearqueue')
        assert ctx.voice.playback(CHAT).title == 'current'
        assert 'third' not in await contents(handlers)
    asyncio.run(scenario())


def test_playnext_repeat_one_and_explicit_skip(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play later')
        await invoke(handlers, '/playnext next')
        await invoke(handlers, '/loop one')
        await invoke(handlers, '/skip')
        assert ctx.voice.playback(CHAT).title == 'next'
        assert 'later' in await contents(handlers)
    asyncio.run(scenario())


def test_failed_skip_and_jump_restore_queue_order(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        for title in ['current', 'first', 'second']:
            await invoke(handlers, '/play ' + title)
        ctx.voice.play.side_effect = VoiceUnavailable('private-token')
        await invoke(handlers, '/skip')
        before = await contents(handlers)
        response = await invoke(handlers, '/jump 2')
        assert 'private-token' not in response.reply.await_args.args[0]
        assert await contents(handlers) == before
        assert ctx.voice.playback(CHAT).title == 'current'
    asyncio.run(scenario())


def test_volume_state_changes_only_after_acknowledgement(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        await invoke(handlers, '/volume 140')
        ctx.voice.volume.assert_awaited_once_with(CHAT, 140)
        ctx.voice.volume.return_value = False
        await invoke(handlers, '/volumeup')
        request = await invoke(handlers, '/volume')
        assert '140%' in request.reply.await_args.args[0]
        ctx.voice.volume.return_value = None
        await invoke(handlers, '/volumedown')
        ctx.voice.volume.assert_awaited_with(CHAT, 120)
    asyncio.run(scenario())


@pytest.mark.parametrize('command', ['/move 0 2', '/remove 999', '/jump -1',
                                     '/loop invalid', '/volume 201', '/shuffle unexpected'])
def test_invalid_music_controls_do_not_change_playback(tmp_path, monkeypatch, command):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play next')
        before = await contents(handlers)
        await invoke(handlers, command)
        assert await contents(handlers) == before
        assert ctx.voice.play.call_count == 1
    asyncio.run(scenario())


def test_replay_and_history_are_isolated_per_group(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play next')
        await invoke(handlers, '/replay')
        assert ctx.voice.play.call_count == 2
        response = await invoke(handlers, '/history')
        assert 'current' in response.reply.await_args.args[0]
        other = await invoke(handlers, '/history', chat=-200)
        assert 'current' not in other.reply.await_args.args[0]
    asyncio.run(scenario())


def test_queue_limit_and_repeat_modes_are_bounded():
    queue = ChatQueue(current=Track('current', 'source'))
    for i in range(49):
        queue.add(Track(str(i), 'source'))
    with pytest.raises(ValueError, match='full'):
        queue.add(Track('too many', 'source'))
    queue.loop = True
    assert queue.advance().title == 'current'
    assert queue.advance(force=True).title == '0'
    queue.loop = False
    queue.repeat_all = True
    assert queue.advance().title == '1'
    assert queue.waiting[-1].title == '0'
    queue.stop()
    assert not queue.repeat_all and not queue.loop and queue.size == 0


def test_concurrent_requests_share_chat_lock_but_not_other_groups(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def resolve(request, arg):
            if arg == 'slow':
                entered.set()
                await proceed.wait()
            return 'https://example.test/' + arg, arg
        monkeypatch.setattr(music, 'resolve', resolve)
        first = asyncio.create_task(invoke(handlers, '/play slow'))
        await entered.wait()
        second = asyncio.create_task(invoke(handlers, '/play next'))
        await invoke(handlers, '/play independent', chat=-200)
        assert ctx.voice.playback(-200).title == 'independent'
        proceed.set()
        await asyncio.gather(first, second)
        assert ctx.voice.playback(CHAT).title == 'slow'
        assert 'next' in await contents(handlers)
        assert ctx.voice.play.call_count == 2
    asyncio.run(scenario())


def test_jump_shuffle_and_aliases_keep_current_playback_consistent(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        for title in ['current', 'first', 'second']:
            await invoke(handlers, '/play ' + title)
        await invoke(handlers, '/shuffle')
        assert ctx.voice.playback(CHAT).title == 'current'
        await invoke(handlers, '/jump 1')
        assert ctx.voice.playback(CHAT).title in ('first', 'second')
        response = await invoke(handlers, '/q')
        assert response.reply.await_count == 1
        await invoke(handlers, '/end')
        assert ctx.voice.playback(CHAT) is None
        assert 'Nothing queued' in await contents(handlers)
    asyncio.run(scenario())


def test_playnext_cannot_bypass_queue_admin_permissions(tmp_path, monkeypatch):
    async def scenario():
        ctx, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        await invoke(handlers, '/play next')
        response = await invoke(handlers, '/playnext unwanted', uid=STRANGER)
        assert 'administrators' in response.reply.await_args.args[0]
        assert 'unwanted' not in await contents(handlers)
    asyncio.run(scenario())


def test_untrusted_track_title_is_escaped_in_queue_notifications(tmp_path, monkeypatch):
    async def scenario():
        _, _, handlers = wire(tmp_path, monkeypatch)
        await invoke(handlers, '/play current')
        request = await invoke(handlers, '/play <script>')
        body = request.reply.await_args.args[0]
        assert '<script>' not in body and '&lt;script&gt;' in body
    asyncio.run(scenario())
