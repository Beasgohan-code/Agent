"""Membership transitions and literal placeholder values."""
import asyncio
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatMemberStatus as S

from agent.modules import welcome
import test_groups
from test_groups import FakeClient, FakeMessage, update


@pytest.fixture
def ctx(tmp_path):
    return test_groups.ctx.__wrapped__(tmp_path)


def test_placeholder_values_are_not_substituted_again():
    text = welcome.render('{mention} {name} {chat} {count}',
        user=SimpleNamespace(id=22, first_name='{chat}<b>'),
        chat=SimpleNamespace(title='{count}'), count=42)
    assert text.count('{chat}') == 2 and '{count}' in text
    assert '<b>' not in text and '&lt;b&gt;' in text


@pytest.mark.parametrize('status,flag,expected', [(S.RESTRICTED, True, True), (S.RESTRICTED, False, False),
    (S.RESTRICTED, None, None), (S.ADMINISTRATOR, None, True), (S.OWNER, None, True), (None, None, None)])
def test_membership_is_tri_state(status, flag, expected):
    assert welcome.membership(SimpleNamespace(status=status, is_member=flag)) is expected


def test_expanded_greeting_is_not_silently_cut():
    with pytest.raises(ValueError):
        welcome.render('{mention}' * 150, user=SimpleNamespace(id=22, first_name='Name'*20),
                       chat=SimpleNamespace(title='group'), count=None)


def test_admin_departure_and_restricted_member_no_false_join(ctx):
    async def scenario():
        ctx.chats.set_greeting(-100900, 'goodbye', 'Bye {name}')
        ctx.chats.set_greeting(-100900, 'welcome', 'Hi {name}')
        client = FakeClient()
        await welcome.watch(ctx)(client, update(new_status=S.LEFT, old_status=S.ADMINISTRATOR))
        assert len([call for call in client.calls if call[0] == 'send']) == 1
        client.calls.clear()
        event = update(new_status=S.MEMBER, old_status=S.RESTRICTED)
        event.old_chat_member.is_member = True
        await welcome.watch(ctx)(client, event)
        assert not client.calls
    asyncio.run(scenario())


def test_configuration_preserves_newlines_and_rejects_oversized_text(ctx):
    async def scenario():
        client = FakeClient()
        _, commands = welcome.build(ctx)
        await commands['setwelcome'](client, FakeMessage('/setwelcome Hi\n\n{mention}'))
        assert ctx.chats.greeting(-100900, 'welcome')['text'] == 'Hi\n\n{mention}'
        await commands['setwelcome'](client, FakeMessage('/setwelcome ' + 'x'*1501))
        assert ctx.chats.greeting(-100900, 'welcome')['text'] == 'Hi\n\n{mention}'
        await commands['welcome'](client, FakeMessage('/welcome off extra'))
        assert ctx.chats.greeting(-100900, 'welcome')['enabled']
        request = FakeMessage('/welcome')
        request.from_user = None
        await commands['welcome'](client, request)
        assert 'personal Telegram' in request.replies[-1]
    asyncio.run(scenario())
