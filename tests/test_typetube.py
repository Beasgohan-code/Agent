import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules.leech import typetube, LeechError
from agent.modules import leech
from test_plugins import make_ctx, FakeMessage, OWNER


@pytest.mark.parametrize('url', ['https://youtu.be/dQw4w9WgXcQ', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=ignored', 'https://youtube.com/shorts/dQw4w9WgXcQ'])
def test_youtube_canonicalization(url):
    assert typetube.youtube_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


@pytest.mark.parametrize('url', ['https://youtube.com/playlist?list=abc', 'https://youtube.com/@channel', 'http://youtu.be/dQw4w9WgXcQ'])
def test_unsupported_youtube_input_refused(url):
    with pytest.raises(LeechError):
        typetube.youtube_url(url)


def test_type_tube_bridge_validates_output_and_kills_cancelled_process(monkeypatch):
    async def scenario():
        monkeypatch.setattr(typetube, 'available', lambda: True)
        monkeypatch.setattr(typetube, 'check_target', AsyncMock())
        process = NS(returncode=0, communicate=AsyncMock(return_value=(json.dumps({'url':'https://rr1.googlevideo.com/audio?secret=x','title':'Song','mime':'audio/mp4; codecs="mp4a"'}).encode(), None)), kill=lambda: None, wait=AsyncMock())
        monkeypatch.setattr(typetube.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
        assert await typetube.resolve_audio('https://youtu.be/dQw4w9WgXcQ') == ('https://rr1.googlevideo.com/audio?secret=x', 'Song.m4a')
        process.communicate.return_value = (b'{"url":"https://evil.example/file","title":"bad","mime":"audio/mp4"}', None)
        with pytest.raises(LeechError, match='TypeTube could not resolve'):
            await typetube.resolve_audio('https://youtu.be/dQw4w9WgXcQ')
        process.returncode = None
        def kill():
            process.returncode = -9
        process.kill = kill
        process.communicate.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await typetube.resolve_audio('https://youtu.be/dQw4w9WgXcQ')
        process.wait.assert_awaited_once()
    asyncio.run(scenario())


def test_youtube_audio_reaches_existing_job_delivery_and_cleanup(tmp_path, monkeypatch):
    async def scenario():
        ctx = make_ctx(tmp_path)
        monkeypatch.setattr(leech, 'check_target', AsyncMock())
        monkeypatch.setattr(leech, 'resolve_audio', AsyncMock(return_value=('https://rr1.googlevideo.com/audio?token=private', 'Song.m4a')))
        paths = []
        async def download(url, target, **kwargs):
            assert url.startswith('https://rr1.googlevideo.com/')
            target.write_bytes(b'audio'); paths.append(target); return 5
        monkeypatch.setattr(leech, 'download', download)
        client = NS(send_document=AsyncMock(), edit_message_text=AsyncMock())
        msg = FakeMessage('/leech https://youtu.be/dQw4w9WgXcQ')
        await leech.build(ctx)[1]['leech'](client, msg)
        job = ctx.jobs.for_owner(OWNER)[0]
        await job.task
        assert job.state.value == 'done'
        assert client.send_document.await_args.kwargs['file_name'] == 'Song.m4a'
        assert paths and not paths[0].exists() and not paths[0].parent.exists()
        assert 'private' not in job.label and 'private' not in '\n'.join(msg.replies)
    asyncio.run(scenario())
