"""Stale callbacks must never lift unrelated restrictions."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatMemberStatus

from agent.modules.security.verify import Verifier, parse_press
from test_plugins import make_ctx, FakeClient, FakeQuery, CHAT

USER = 99


async def pending(verifier):
    task = asyncio.create_task(asyncio.Event().wait())
    verifier.pending[(CHAT, USER)] = task
    verifier.prompts[(CHAT, USER)] = (CHAT, 777)
    return task


def test_stale_button_cannot_unrestrict_anyone(tmp_path):
    async def scenario():
        verifier = Verifier(make_ctx(tmp_path))
        client = FakeClient()
        query = FakeQuery('', USER)
        await verifier.on_press(client, query, f'{CHAT}:{USER}')
        assert not client.calls
        assert 'no longer active' in query.answers[-1]
    asyncio.run(scenario())


@pytest.mark.parametrize('mismatch', ['group', 'prompt'])
def test_callback_is_bound_to_origin_group_and_prompt(tmp_path, mismatch):
    async def scenario():
        verifier = Verifier(make_ctx(tmp_path))
        task = await pending(verifier)
        client = FakeClient()
        query = FakeQuery('', USER)
        if mismatch == 'group':
            query.message.chat.id = -200
        else:
            query.message.id = 778
        await verifier.on_press(client, query, f'{CHAT}:{USER}')
        assert not client.calls
        assert verifier.pending[(CHAT, USER)] is task
        await verifier.shutdown()
    asyncio.run(scenario())


def test_failed_unrestriction_preserves_session_and_timeout(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        verifier = Verifier(ctx)
        task = await pending(verifier)
        client = FakeClient()
        client.restrict_chat_member = AsyncMock(side_effect=RuntimeError('API failed'))
        await verifier.on_press(client, FakeQuery('', USER), f'{CHAT}:{USER}')
        assert verifier.pending[(CHAT, USER)] is task
        assert not task.cancelled()
        assert not ctx.chats.history(CHAT)
        await verifier.shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [None, ChatMemberStatus.LEFT, ChatMemberStatus.BANNED,
                                   ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER])
def test_changed_or_unknown_membership_is_not_unrestricted(tmp_path, status):
    async def scenario():
        from types import SimpleNamespace
        verifier = Verifier(make_ctx(tmp_path))
        await pending(verifier)
        client = FakeClient()
        client.get_chat_member = AsyncMock(return_value=SimpleNamespace(status=status))
        await verifier.on_press(client, FakeQuery('', USER), f'{CHAT}:{USER}')
        assert not client.calls
        await verifier.shutdown()
    asyncio.run(scenario())


def test_verified_member_receives_current_group_defaults(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        verifier = Verifier(ctx)
        task = await pending(verifier)
        client = FakeClient()
        baseline = (await client.get_chat(CHAT)).permissions
        from types import SimpleNamespace
        client.get_chat = AsyncMock(return_value=SimpleNamespace(permissions=baseline))
        client.restrict_chat_member = AsyncMock()
        query = FakeQuery('', USER)
        await verifier.on_press(client, query, f'{CHAT}:{USER}')
        await asyncio.gather(task, return_exceptions=True)
        assert client.restrict_chat_member.await_args.args[2] is baseline
        assert baseline.can_send_photos is False
        assert not verifier.pending
        assert len(query.answers) == 1
        assert [e['action'] for e in ctx.chats.history(CHAT)] == ['verify']
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [None, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER,
                                   ChatMemberStatus.LEFT, ChatMemberStatus.BANNED])
def test_timeout_does_not_kick_unknown_protected_or_departed_members(tmp_path, status):
    async def scenario():
        from types import SimpleNamespace
        ctx = make_ctx(tmp_path)
        verifier = Verifier(ctx)
        client = FakeClient()
        client.get_chat_member = AsyncMock(return_value=SimpleNamespace(status=status))
        task = asyncio.create_task(verifier._remove_later(client, CHAT, USER, 0))
        verifier.pending[(CHAT, USER)] = task
        await task
        assert not client.calls
        assert all(e['action'] != 'verify:timeout' for e in ctx.chats.history(CHAT))
    asyncio.run(scenario())


@pytest.mark.parametrize('payload', ['--100:99', '-100:-99', '100:99', '-100:0', '-100:99:1',
                                     '-999999999999999999999:1', '-100:999999999999999999999'])
def test_invalid_callback_ids_are_rejected(payload):
    assert parse_press(payload) is None


def join_update():
    from types import SimpleNamespace
    from pyrogram.enums import ChatType
    return SimpleNamespace(
        chat=SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP),
        old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT),
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER,
            user=SimpleNamespace(id=USER, first_name='<b>new</b>', is_bot=False)),
    )


def test_failed_prompt_delivery_rolls_back_restriction(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.put(CHAT, 'verify_enabled', True)
        verifier = Verifier(ctx)
        client = FakeClient()
        client.send_message = AsyncMock(side_effect=RuntimeError('cannot send'))
        client.restrict_chat_member = AsyncMock()
        await verifier.on_member_update(client, join_update())
        calls = client.restrict_chat_member.await_args_list
        assert len(calls) == 2
        assert calls[0].args[2].can_send_messages is False
        assert calls[1].args[2].can_send_messages is True
        assert calls[1].args[2].can_send_photos is False
        assert not verifier.pending
        assert ctx.chats.history(CHAT)[0]['action'] == 'verify:prompt_failed'
    asyncio.run(scenario())


def test_duplicate_join_updates_create_one_prompt_and_timer(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.put(CHAT, 'verify_enabled', True)
        verifier = Verifier(ctx)
        client = FakeClient()
        await asyncio.gather(*(verifier.on_member_update(client, join_update()) for _ in range(2)))
        assert sum(call[0] == 'send' for call in client.calls) == 1
        assert len(verifier.pending) == 1
        assert '&lt;b&gt;new&lt;/b&gt;' in next(call[1] for call in client.calls if call[0] == 'send')
        await verifier.shutdown()
    asyncio.run(scenario())


def test_failed_membership_lookup_does_not_restrict_joiner(tmp_path):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.put(CHAT, 'verify_enabled', True)
        verifier = Verifier(ctx)
        client = FakeClient()
        client.get_chat_member = AsyncMock(side_effect=RuntimeError('unavailable'))
        await verifier.on_member_update(client, join_update())
        assert not client.calls
        assert not verifier.pending
    asyncio.run(scenario())
