"""Channel-share settings are isolated, awaited and safe under concurrent edits."""
import asyncio
import os
import uuid

import pytest

from agent.platform.db import Database


@pytest.mark.asyncio
async def test_channel_share_settings_merge_restart_and_tenant_isolation():
    from agent.platform.channel_shares import ChannelShares
    url = os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable storage required')
    scope = 'channelshares:' + uuid.uuid4().hex
    dbs = [Database(url, scope=scope), Database(url, scope=scope), Database(url, scope=scope + ':other')]
    try:
        for db in dbs:
            assert await db.connect()
        first, second, other = [ChannelShares(db) for db in dbs]
        row = await first.configure(-100, actor=11)
        assert row['enabled'] is True and row['auto_approve'] is False
        await asyncio.gather(first.configure(-100, actor=11, auto_approve=True),
                             second.configure(-100, actor=11, enabled=False))
        row = await ChannelShares(dbs[0]).get(-100)
        assert row['enabled'] is False and row['auto_approve'] is True
        assert await other.get(-100) is None
        assert len(await second.list()) == 1
        assert await other.list() == []
    finally:
        for db in dbs:
            await db.close()


@pytest.mark.asyncio
async def test_channel_share_quota_is_serialized_and_updates_still_work():
    from agent.platform.channel_shares import ChannelShares
    url = os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable storage required')
    db = Database(url, scope='channelquota:' + uuid.uuid4().hex)
    assert await db.connect()
    try:
        stores = [ChannelShares(db), ChannelShares(db)]
        for n in range(19):
            await stores[0].configure(-100-n, actor=11)
        results = await asyncio.gather(*(stores[i].configure(-200-i, actor=11) for i in range(2)), return_exceptions=True)
        assert sum(isinstance(r, ValueError) for r in results) == 1
        assert len(await stores[0].list()) == 20
        await stores[1].configure(-100, actor=11, auto_approve=True)
        assert (await stores[0].get(-100))['auto_approve'] is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_channel_share_settings_reject_invalid_inputs_without_storage():
    from agent.platform.channel_shares import ChannelShares
    store = ChannelShares(None)
    for channel, actor, fields in [(True, 11, {}), (-100, True, {}), (1, 11, {}),
                                   (-100, 11, {'auto_approve': 'true'}),
                                   (-100, 11, {'enabled': 1})]:
        with pytest.raises(ValueError):
            await store.configure(channel, actor=actor, **fields)
    with pytest.raises(RuntimeError):
        await store.configure(-100, actor=11)
