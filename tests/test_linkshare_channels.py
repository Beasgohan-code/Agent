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


@pytest.mark.asyncio
async def test_channel_genlink_checks_authority_and_reports_partial_invites(monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules.linkshare.subscription import build_channels
    row = {'channel_id': -100123, 'enabled': True, 'auto_approve': False}
    store = NS(get=AsyncMock(return_value=row), list=AsyncMock(return_value=[row]), configure=AsyncMock(return_value=row))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = NS(settings=NS(owner_id=11, bot_id=99), db=None)
    msg = NS(text='/genlink -100123', chat=NS(id=11, type=ChatType.PRIVATE), from_user=NS(id=11), reply=AsyncMock())
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=NS(status=S.ADMINISTRATOR, privileges=NS(can_invite_users=True))),
                create_chat_invite_link=AsyncMock(side_effect=[NS(invite_link='https://t.me/+normal'), RuntimeError('private-token')]))
    await build_channels(ctx)(client, msg)
    assert client.create_chat_invite_link.await_count == 2
    assert client.create_chat_invite_link.await_args_list[0].kwargs['member_limit'] == 1
    assert client.create_chat_invite_link.await_args_list[1].kwargs['creates_join_request'] is True
    body = str(msg.reply.await_args.args[0])
    assert 'https://t.me/+normal' in body and 'not confirmed' in body
    assert 'private-token' not in body
    client.create_chat_invite_link.reset_mock()
    msg.from_user.id = 22
    await build_channels(ctx)(client, msg)
    client.create_chat_invite_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_mode_and_add_require_live_invite_rights(monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules.linkshare.subscription import build_channels
    row = {'channel_id': -100123, 'enabled': True, 'auto_approve': False}
    store = NS(get=AsyncMock(return_value=row), configure=AsyncMock(return_value=row))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = NS(settings=NS(owner_id=11, bot_id=99), db=None)
    msg = NS(text='/genlink mode -100123 auto', chat=NS(id=11, type=ChatType.PRIVATE), from_user=NS(id=11), reply=AsyncMock())
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=NS(status=S.ADMINISTRATOR, privileges=NS(can_invite_users=False))))
    command = build_channels(ctx)
    await command(client, msg)
    store.configure.assert_not_awaited()
    client.get_chat_member.return_value.privileges.can_invite_users = True
    await command(client, msg)
    store.configure.assert_awaited_once_with(-100123, actor=11, auto_approve=True)
    assert 'approval worker' in str(msg.reply.await_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['disabled', 'unmanaged', 'rights_lost', 'no_ack', 'provider', 'bad_url'])
async def test_channel_invites_refuse_uncertain_effects_without_retry(monkeypatch, failure, caplog):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules.linkshare.subscription import build_channels
    row = {'channel_id': -100123, 'enabled': failure != 'disabled', 'auto_approve': False}
    store = NS(get=AsyncMock(return_value=None if failure == 'unmanaged' else row))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = NS(settings=NS(owner_id=11, bot_id=99), db=None)
    msg = NS(text='/genlink -100123', chat=NS(id=11, type=ChatType.PRIVATE), from_user=NS(id=11), reply=AsyncMock())
    admin = NS(status=S.ADMINISTRATOR, privileges=NS(can_invite_users=True))
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=admin), create_chat_invite_link=AsyncMock(return_value=None))
    if failure == 'rights_lost':
        client.get_chat_member.side_effect = [admin, admin, NS(status=S.MEMBER)]
    if failure == 'provider':
        client.create_chat_invite_link.side_effect = RuntimeError('private-invite-secret')
    if failure == 'bad_url':
        client.create_chat_invite_link.return_value = NS(invite_link='https://evil.test/private-invite-secret')
    await build_channels(ctx)(client, msg)
    assert client.create_chat_invite_link.await_count == (1 if failure in ('no_ack', 'provider', 'bad_url') else 0)
    body = str(msg.reply.await_args.args[0])
    assert 'private-invite-secret' not in body and 'private-invite-secret' not in caplog.text
    assert 'https://evil.test' not in body


@pytest.mark.asyncio
async def test_existing_genlink_routes_channel_management_without_new_command(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.modules import linkshare
    from test_plugins import make_ctx
    from test_archive_links import request
    store = NS(list=AsyncMock(return_value=[]))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = make_ctx(tmp_path)
    commands = linkshare.build(ctx)[1]
    await commands['genlink'](None, request('/genlink channels'))
    store.list.assert_awaited_once()
    assert set(commands) == set(linkshare.MANIFEST.commands)
