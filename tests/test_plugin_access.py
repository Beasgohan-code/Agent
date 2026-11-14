"""Unit contract tests. Real PostgreSQL races live in test_plugin_access_pg.py."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

from agent.platform.plugin_access import PluginAccess, AccessError


def message(group=-100):
    return SimpleNamespace(chat=SimpleNamespace(id=group, type=ChatType.SUPERGROUP),
                           from_user=SimpleNamespace(id=22))


def client(admin=True):
    return SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(
        status=ChatMemberStatus.ADMINISTRATOR if admin else ChatMemberStatus.MEMBER,
        privileges=SimpleNamespace(can_manage_chat=admin))))


class Connection:
    def __init__(self, values=()):
        self.fetchval = AsyncMock(side_effect=values)
        self.fetch = AsyncMock(return_value=[])
        self.execute = AsyncMock()
        self.committed = False

    @asynccontextmanager
    async def transaction(self):
        yield self
        self.committed = True


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def access(values=()):
    conn = Connection(values)
    service = PluginAccess(SimpleNamespace(connected=True, scope='main:123', _pool=Pool(conn)), owner_id=11)
    return service, conn


def test_activation_checks_approval_then_group_lock_before_counting():
    async def scenario():
        service, conn = access([True, None, 2])
        assert await service.activate(client(), message(), 'music')
        assert conn.committed
        assert 'FOR SHARE' in conn.fetchval.await_args_list[0].args[0]
        assert 'pg_advisory_xact_lock' in conn.execute.await_args_list[0].args[0]
        assert conn.execute.await_args_list[0].args[1] == 'agent:plugins:main:123:-100'
        assert 'INSERT INTO agent_group_plugins' in conn.execute.await_args_list[1].args[0]
    asyncio.run(scenario())


def test_fourth_slot_refused_without_insert_or_history():
    async def scenario():
        service, conn = access([True, None, 3])
        with pytest.raises(AccessError, match='three'):
            await service.activate(client(), message(), 'music')
        assert conn.execute.await_count == 1  # advisory lock only
        assert not conn.committed
    asyncio.run(scenario())


def test_approval_rechecked_inside_transaction():
    async def scenario():
        service, conn = access([False])
        with pytest.raises(AccessError, match='not approved'):
            await service.activate(client(), message(), 'music')
        conn.execute.assert_not_awaited()
    asyncio.run(scenario())


def test_unauthorized_admin_does_not_touch_database():
    async def scenario():
        service, conn = access()
        with pytest.raises(AccessError, match='permission'):
            await service.activate(client(False), message(), 'music')
        conn.fetchval.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('actor', [None, 22, True, -11])
def test_only_owner_can_approve(actor):
    service, conn = access()
    with pytest.raises(AccessError, match='Owner'):
        asyncio.run(service.approve('music', actor_id=actor))
    conn.execute.assert_not_awaited()


def test_no_postgres_means_no_activation_fallback():
    service = PluginAccess(SimpleNamespace(connected=False), owner_id=11)
    with pytest.raises(AccessError, match='no local fallback'):
        asyncio.run(service.activate(client(), message(), 'music'))


@pytest.mark.parametrize('slug', ['moderation', 'ops', 'security', 'unknown'])
def test_mandatory_and_unknown_plugins_cannot_consume_slots(slug):
    service, conn = access()
    with pytest.raises(AccessError):
        asyncio.run(service.activate(client(), message(), slug))
    conn.execute.assert_not_awaited()


def test_revocation_marks_resources_and_removes_activations_in_same_transaction():
    async def scenario():
        service, conn = access()
        conn.fetch.return_value = [{'group_id': -100}, {'group_id': -200}]
        assert await service.revoke('music', actor_id=11) == [-100, -200]
        assert conn.committed
        statements = [call.args[0] for call in conn.execute.await_args_list]
        assert 'approved=FALSE' in statements[0]
        assert any("cleanup_pending" in sql for sql in statements)
        assert all(call.args[1] == 'main:123' for call in conn.execute.await_args_list)
    asyncio.run(scenario())
