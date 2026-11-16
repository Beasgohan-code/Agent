"""The demo edits an actual card and never pretends to run an AI task."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from pyrogram.enums import ChatType, ButtonStyle
from agent.modules import utilities
from agent.ui.theme import Theme


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected', [('', 'completed'), (' fail', 'simulated failure')])
async def test_demo_updates_same_card(mode, expected):
    value = NS(theme=Theme(custom_emoji={}), settings=NS(owner_id=11))
    manifest, commands = utilities.build(value)
    assert 'gu' in manifest.commands
    sent = NS()
    message = NS(text='/gu'+mode, chat=NS(id=22, type=ChatType.PRIVATE), from_user=NS(id=22))
    with patch('agent.modules.utilities.reply', AsyncMock(return_value=sent)) as send, patch('agent.modules.utilities.edit', AsyncMock()) as edit:
        await commands['gu'](None, message)
    send.assert_awaited_once()
    assert edit.await_args.args[0] is sent
    assert expected in str(edit.await_args.args[1]).lower()
    buttons = edit.await_args.kwargs['reply_markup'].inline_keyboard[0]
    assert buttons[0].style == ButtonStyle.PRIMARY


@pytest.mark.asyncio
async def test_group_nonadmin_and_bad_arguments_never_run_demo():
    value = NS(theme=Theme(custom_emoji={}), settings=NS(owner_id=11))
    handler = utilities.build(value)[1]['gu']
    with patch('agent.modules.utilities.reply', AsyncMock()) as send, patch('agent.modules.utilities.edit', AsyncMock()) as edit, patch('agent.modules.utilities.is_moderator', AsyncMock(return_value=False)) as auth:
        await handler(None, NS(text='/gu', chat=NS(id=-100, type=ChatType.SUPERGROUP), from_user=NS(id=22)))
        auth.assert_awaited_once()
        assert 'admin' in str(send.await_args.args[1]).lower()
        await handler(None, NS(text='/gu anything', chat=NS(id=22, type=ChatType.PRIVATE), from_user=NS(id=22)))
        assert 'Usage' in str(send.await_args.args[1])
        edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_failure_is_unconfirmed_and_redacted():
    value = NS(theme=Theme(custom_emoji={}), settings=NS(owner_id=11))
    message = NS(text='/gu', chat=NS(id=22, type=ChatType.PRIVATE), from_user=NS(id=22))
    with patch('agent.modules.utilities.reply', AsyncMock(return_value=NS())) as send, patch('agent.modules.utilities.edit', AsyncMock(side_effect=RuntimeError('SECRET'))):
        await utilities.build(value)[1]['gu'](None, message)
    assert send.await_count == 2
    assert 'unconfirmed' in str(send.await_args.args[1]) and 'SECRET' not in str(send.await_args.args[1])
