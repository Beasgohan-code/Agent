"""Direct uploads only opt in on specialized FileStore clones."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules import filestore
from test_filestore_clone_frontdoor import ctx
from test_archive_links import request, client


@pytest.mark.asyncio
@pytest.mark.parametrize('scope,uid,media,copies', [
    ('clone:111111111', 11, True, 1),
    ('main', 11, True, 0),
    ('clone:111111111', 22, True, 0),
    ('clone:111111111', 11, False, 0),
])
async def test_direct_upload_scope_and_authorization(scope, uid, media, copies):
    value = ctx(scope=scope)
    value.db = NS(connected=True, _pool=object())
    filestore.build(value)
    flow = value._filestore_conversation
    flow.generate = AsyncMock()
    item = request('', uid=uid, mid=123)
    item.document = NS(file_id='file') if media else None
    bot = client()
    await filestore.extra_handlers(value)[0].callback(bot, item)
    assert bot.copy_message.await_count == copies
    assert flow.generate.await_count == copies
