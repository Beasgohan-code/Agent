"""All supported FileStore media types use the same bounded link lifecycle."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import linkshare
from agent.modules.filestore.vault import MAX_BOT_DOWNLOAD
from test_plugins import make_ctx, FakeMessage, OWNER


@pytest.mark.parametrize('kind', ['document', 'video', 'audio', 'voice', 'animation', 'photo'])
def test_channel_genlink_never_ingests_any_file_type(tmp_path, kind):
    async def scenario():
        ctx = make_ctx(tmp_path)
        from pyrogram.enums import ChatType
        media = SimpleNamespace(file_name='payload.dat', file_size=5)
        replied = SimpleNamespace(**{kind: media}, download=AsyncMock())
        request = FakeMessage('/genlink 48 2', reply_to=replied)
        request.chat = SimpleNamespace(id=OWNER, type=ChatType.PRIVATE)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
        assert '/settings' in request.replies[-1]
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['document', 'audio', 'photo'])
def test_oversized_replied_media_is_not_ingested(tmp_path, kind):
    async def scenario():
        ctx = make_ctx(tmp_path)
        replied = SimpleNamespace(**{kind: SimpleNamespace(file_size=MAX_BOT_DOWNLOAD+1)}, download=AsyncMock())
        request = FakeMessage('/genlink', reply_to=replied)
        await linkshare.build(ctx)[1]['genlink'](None, request)
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
    asyncio.run(scenario())


def test_removed_ingest_does_not_attempt_empty_download(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        replied = SimpleNamespace(voice=SimpleNamespace(file_size=1), download=AsyncMock(return_value=None))
        await linkshare.build(ctx)[1]['genlink'](None, FakeMessage('/genlink', reply_to=replied))
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
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


def test_unknown_size_cannot_reenable_retired_ingest(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        replied = SimpleNamespace(audio=SimpleNamespace(file_size=0), download=AsyncMock())
        await linkshare.build(ctx)[1]['genlink'](None, FakeMessage('/genlink', reply_to=replied))
        replied.download.assert_not_awaited()
        assert not ctx.links.owned(OWNER) and not ctx.storage.list_owned(OWNER)
    asyncio.run(scenario())
