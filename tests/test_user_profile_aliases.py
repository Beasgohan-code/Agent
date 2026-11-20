"""Identity commands share one renderer and never fabricate private user data."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.modules import utilities
from agent.ui.theme import Theme


def setup(text):
    value = NS(theme=Theme(custom_emoji={}),settings=NS(owner_id=11),chats=None)
    item = NS(text=text,from_user=NS(id=22,first_name='Caller'),chat=NS(id=22),reply=AsyncMock(),reply_to_message=NS(from_user=NS(id=33,first_name='Reply user')))
    client = NS(get_users=AsyncMock(return_value=NS(id=44,first_name='<Target>',username='target')),get_chat_member=AsyncMock(side_effect=RuntimeError('unavailable')))
    return utilities.build(value)[1],item,client


@pytest.mark.asyncio
async def test_myinfo_ignores_reply_and_shows_caller():
    commands,item,client=setup('/myinfo')
    await commands['myinfo'](client,item)
    assert 'Caller' in str(item.reply.await_args.args[0])
    assert 'Reply user' not in str(item.reply.await_args.args[0])
    client.get_users.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('command',['info','userinfo'])
async def test_explicit_username_uses_shared_profile_card(command):
    commands,item,client=setup('/'+command+' @target')
    await commands[command](client,item)
    client.get_users.assert_awaited_once_with('@target')
    text=str(item.reply.await_args.args[0])
    assert '&lt;Target&gt;' in text and '<Target>' not in text
    assert '44' in text and 'Reply user' not in text


@pytest.mark.asyncio
async def test_bad_lookup_is_redacted():
    commands,item,client=setup('/userinfo @target')
    client.get_users.side_effect=ValueError('SECRET')
    await commands['userinfo'](client,item)
    assert 'SECRET' not in str(item.reply.await_args.args[0])
    assert 'unavailable' in str(item.reply.await_args.args[0]).lower()


@pytest.mark.asyncio
async def test_private_profile_does_not_make_meaningless_membership_queries():
    commands, item, client = setup('/myinfo')
    await commands['myinfo'](client, item)
    client.get_chat_member.assert_not_awaited()
    assert 'not applicable' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_myinfo_does_not_fetch_an_unloaded_reply():
    commands, item, client = setup('/myinfo')
    item.reply_to_message = None
    item.reply_to_message_id = 9
    client.get_messages = AsyncMock()
    await commands['myinfo'](client, item)
    client.get_messages.assert_not_awaited()
    assert 'Caller' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['info', 'userinfo'])
async def test_explicit_identity_bypasses_unavailable_reply(command):
    commands, item, client = setup('/' + command + ' @target')
    item.reply_to_message = None
    item.reply_to_message_id = 9
    client.get_messages = AsyncMock(side_effect=RuntimeError('must not load reply'))
    await commands[command](client, item)
    client.get_messages.assert_not_awaited()
    assert '&lt;Target&gt;' in str(item.reply.await_args.args[0])


@pytest.mark.asyncio
async def test_profile_membership_timeout_is_bounded_and_public_identity_survives(monkeypatch):
    import asyncio
    commands, item, client = setup('/myinfo')
    item.chat.id = -22
    reached = asyncio.Event()
    async def blocked(*args):
        reached.set()
        await asyncio.Event().wait()
    client.get_chat_member = AsyncMock(side_effect=blocked)
    original = asyncio.wait_for
    async def fast_timeout(awaitable, *, timeout):
        assert timeout == 5
        return await original(awaitable, timeout=0.01)
    monkeypatch.setattr(utilities.asyncio, 'wait_for', fast_timeout)
    await commands['myinfo'](client, item)
    assert reached.is_set()
    body = str(item.reply.await_args.args[0])
    assert 'Caller' in body and 'unavailable' in body


@pytest.mark.asyncio
async def test_profile_cancellation_propagates_without_sending_a_card():
    import asyncio
    commands, item, client = setup('/myinfo')
    item.chat.id = -22
    reached = asyncio.Event()
    stopped = asyncio.Event()
    async def blocked(*args):
        reached.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    client.get_chat_member = AsyncMock(side_effect=blocked)
    task = asyncio.create_task(commands['myinfo'](client, item))
    await asyncio.wait_for(reached.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    item.reply.assert_not_awaited()
