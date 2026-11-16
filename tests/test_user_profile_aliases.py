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
