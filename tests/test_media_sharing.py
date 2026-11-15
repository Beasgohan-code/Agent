"""All supported FileStore media types use the same bounded link lifecycle."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import linkshare
from agent.modules.filestore.vault import MAX_BOT_DOWNLOAD
from test_plugins import make_ctx, FakeMessage, OWNER


@pytest.mark.parametrize('kind', ['document', 'video', 'audio', 'voice', 'animation', 'photo'])
def test_genlink_supports_filestore_media_types(tmp_path, kind):
    async def scenario():
        ctx = make_ctx(tmp_path)
        source = tmp_path / 'source'
        source.write_bytes(b'media')
        media = SimpleNamespace(file_name='payload.dat', file_size=5)
        if kind == 'photo':
            media = [SimpleNamespace(file_size=2), SimpleNamespace(file_size=5)]
        replied = SimpleNamespace(**{kind: media}, download=AsyncMock(return_value=str(source)))
        request = FakeMessage('/genlink 48 2', reply_to=replied)
        client = SimpleNamespace(me=SimpleNamespace(username='agentbot'))
        await linkshare.build(ctx)[1]['genlink'](client, request)
        record = ctx.links.owned(OWNER)[0]
        stored = ctx.storage.get(record.file_id)
        assert stored.owner_id == OWNER and stored.size == 5
        assert record.max_uses == 2
        assert ctx.storage.path_for(stored).read_bytes() == b'media'
        replied.download.assert_awaited_once()
        assert source.read_bytes() == b'media'
        assert stored.name == ('photo.jpg' if kind == 'photo' else 'payload.dat')
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['document', 'audio', 'photo'])
def test_oversized_media_refused_before_download(tmp_path, kind):
    async def scenario():
        ctx = make_ctx(tmp_path)
        media = SimpleNamespace(file_size=MAX_BOT_DOWNLOAD+1)
        if kind == 'photo':
            media = [media]
        replied = SimpleNamespace(**{kind: media}, download=AsyncMock())
        request = FakeMessage('/genlink', reply_to=replied)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
        assert '20 MB' in request.replies[-1]
    asyncio.run(scenario())


def test_empty_download_never_creates_metadata_or_grant(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        replied = SimpleNamespace(voice=SimpleNamespace(file_size=1), download=AsyncMock(return_value=None))
        request = FakeMessage('/genlink', reply_to=replied)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
        assert 'returned no file' in request.replies[-1]
    asyncio.run(scenario())


def test_tier_quota_admission_prevents_download(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.premium = SimpleNamespace(tier=lambda uid: SimpleNamespace(quota_bytes=2))
        replied = SimpleNamespace(audio=SimpleNamespace(file_size=3), download=AsyncMock())
        request = FakeMessage('/genlink', reply_to=replied)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER)
    asyncio.run(scenario())


def test_unknown_size_still_checks_actual_bytes_against_quota(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.premium = SimpleNamespace(tier=lambda uid: SimpleNamespace(quota_bytes=2))
        source = tmp_path / 'large'
        source.write_bytes(b'oversized')
        replied = SimpleNamespace(audio=SimpleNamespace(file_size=0), download=AsyncMock(return_value=str(source)))
        request = FakeMessage('/genlink', reply_to=replied)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        replied.download.assert_awaited_once()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
        assert 'Could not confirm' in request.replies[-1]
    asyncio.run(scenario())
