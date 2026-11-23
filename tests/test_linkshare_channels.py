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
    assert 'Auto mode approves' in str(msg.reply.await_args.args[0])


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


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['auto', 'manual', 'disabled', 'unmanaged', 'storage', 'rights', 'actor', 'spoof'])
async def test_join_approval_only_for_enabled_managed_opt_in_channels(monkeypatch, mode, caplog):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules.linkshare.subscription import approve_request
    row = {'channel_id': -100123, 'enabled': mode != 'disabled', 'auto_approve': mode != 'manual'}
    store = NS(get=AsyncMock(return_value=None if mode == 'unmanaged' else row))
    if mode == 'storage':
        store.get.side_effect = RuntimeError('private-storage-secret')
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = NS(db=None, settings=NS(owner_id=11, bot_id=99))
    user = NS(id=True if mode == 'actor' else 22, is_bot=False)
    update = NS(chat=NS(id=-100123, type=ChatType.CHANNEL), from_user=user)
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100999 if mode == 'spoof' else -100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=NS(status=S.ADMINISTRATOR, privileges=NS(can_invite_users=mode != 'rights'))),
                approve_chat_join_request=AsyncMock(return_value=True))
    await approve_request(ctx, client, update)
    assert client.approve_chat_join_request.await_count == (1 if mode == 'auto' else 0)
    assert 'private-storage-secret' not in caplog.text


@pytest.mark.asyncio
async def test_join_approval_rechecks_policy_and_never_retries_unknown_result(monkeypatch, caplog):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules.linkshare.subscription import approve_request
    row = {'channel_id': -100123, 'enabled': True, 'auto_approve': True}
    store = NS(get=AsyncMock(side_effect=[row, {**row, 'auto_approve': False}]))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    ctx = NS(db=None, settings=NS(owner_id=11, bot_id=99))
    update = NS(chat=NS(id=-100123, type=ChatType.CHANNEL), from_user=NS(id=22, is_bot=False))
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=NS(status=S.OWNER)),
                approve_chat_join_request=AsyncMock(side_effect=RuntimeError('private-request-secret')))
    await approve_request(ctx, client, update)
    client.approve_chat_join_request.assert_not_awaited()
    store.get.side_effect = None
    store.get.return_value = row
    await approve_request(ctx, client, update)
    client.approve_chat_join_request.assert_awaited_once_with(-100123, 22)
    assert 'private-request-secret' not in caplog.text


def test_linkshare_join_request_watcher_is_owned_by_plugin():
    from agent.modules import linkshare
    from pyrogram.handlers import ChatJoinRequestHandler
    from types import SimpleNamespace as NS
    watchers = linkshare.extra_handlers(NS())
    assert len(watchers) == 1
    assert isinstance(watchers[0], ChatJoinRequestHandler)


@pytest.mark.asyncio
@pytest.mark.parametrize('untrusted', [1, 'true', None, [], {}])
async def test_join_approval_requires_exact_boolean_policy(monkeypatch, untrusted):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType
    from agent.modules.linkshare.subscription import approve_request
    store = NS(get=AsyncMock(return_value={'enabled': True, 'auto_approve': untrusted}))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    client = NS(get_chat=AsyncMock(), approve_chat_join_request=AsyncMock())
    await approve_request(NS(db=None), client, NS(chat=NS(id=-100123, type=ChatType.CHANNEL), from_user=NS(id=22)))
    client.get_chat.assert_not_awaited()
    client.approve_chat_join_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_linkshare_never_approves_native_security_guard_queries():
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.modules.linkshare.subscription import approve_request
    client = NS(approve_chat_join_request=AsyncMock(), get_chat=AsyncMock())
    await approve_request(NS(), client, NS(query_id=123))
    client.get_chat.assert_not_awaited()
    client.approve_chat_join_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_settings_reuses_group_route_but_checks_linkshare_runtime(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from agent.modules import group
    from test_plugins import make_ctx
    from test_archive_links import request
    from test_execution_gate import gate
    ctx = make_ctx(tmp_path)
    execution, _, _ = gate()
    ctx.plugin_gate = execution
    store = NS(list=AsyncMock(return_value=[]))
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    handler = group.build(ctx)[1]['settings']
    msg = request('/settings')
    await handler(None, msg)
    store.list.assert_awaited_once()
    assert 'Managed Linkshare channels' in str(msg.reply.await_args.args[0])
    execution.runtime.wants_disabled = lambda slug: True
    await handler(None, request('/settings'))
    assert store.list.await_count == 1
    assert group.MANIFEST.scope_for('settings') == 'all'
    assert group.MANIFEST.scope_for('pin') == 'group'


def test_manifest_command_scope_override_validation():
    from agent.platform.manifest import PluginManifest, PluginRegistry
    from dataclasses import replace
    from unittest.mock import AsyncMock
    base = PluginManifest(slug='shared', name='Shared', version='1', description='test',
                          commands=('settings', 'pin'), scope='group', command_scopes={'settings': 'all'})
    registry = PluginRegistry()
    registry.register(base, {'settings': AsyncMock(), 'pin': AsyncMock()})
    assert base.scope_for('settings') == 'all'
    assert base.scope_for('pin') == 'group'
    for invalid in ({'missing': 'private'}, {'settings': 'unknown'}):
        with pytest.raises(ValueError):
            PluginRegistry().register(replace(base, command_scopes=invalid), {'settings': AsyncMock(), 'pin': AsyncMock()})


@pytest.mark.asyncio
async def test_private_settings_add_uses_channel_checks_and_awaited_save(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from pyrogram.enums import ChatType, ChatMemberStatus as S
    from agent.modules import group
    from test_plugins import make_ctx
    from test_archive_links import request
    from test_execution_gate import gate
    ctx = make_ctx(tmp_path)
    ctx.plugin_gate = gate()[0]
    store = NS(get=AsyncMock(return_value=None), configure=AsyncMock())
    monkeypatch.setattr('agent.platform.channel_shares.ChannelShares', lambda db: store)
    client = NS(get_chat=AsyncMock(return_value=NS(id=-100123, type=ChatType.CHANNEL)),
                get_chat_member=AsyncMock(return_value=NS(status=S.OWNER)))
    handler = group.build(ctx)[1]['settings']
    await handler(client, request('/settings add -100123'))
    store.configure.assert_awaited_once_with(-100123, actor=11, enabled=True)
    denied = request('/settings add -100123', uid=22)
    await handler(client, denied)
    assert store.configure.await_count == 1


@pytest.mark.asyncio
async def test_old_file_creation_surface_is_removed(tmp_path):
    from unittest.mock import AsyncMock
    from agent.modules import linkshare
    from test_plugins import make_ctx
    from test_archive_links import request
    ctx = make_ctx(tmp_path)
    ctx.storage = AsyncMock()
    ctx.links.acreate = AsyncMock()
    manifest, handlers = linkshare.build(ctx)
    assert 'share' not in manifest.commands and 'linkchannel' not in handlers
    for text in ('/genlink', '/genlink 6 3', '/genlink soon'):
        msg = request(text)
        msg.reply_to_message = AsyncMock()
        await handlers['genlink'](None, msg)
        msg.reply_to_message.download.assert_not_awaited()
    ctx.links.acreate.assert_not_awaited()
    ctx.storage.save_path.assert_not_awaited()
