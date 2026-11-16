from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from pyrogram.enums import ChatType, ChatMemberStatus
from agent.modules import moderation


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['dwarn','swarn'])
async def test_warning_variant_admission_and_silence(command):
    value = NS(settings=NS(owner_id=11),chats=NS(aadd_warning=AsyncMock(return_value=1),log=lambda *a,**k: None))
    message = NS(id=10,text='/'+command,chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=NS(id=11),reply_to_message=NS(id=2,chat=NS(id=-100),from_user=NS(id=22)),reply=AsyncMock())
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,privileges=NS(can_restrict_members=True,can_delete_messages=True))),delete_messages=AsyncMock(return_value=True))
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), patch('agent.modules.moderation.warn_policy', return_value=(3,'mute')), patch('agent.modules.moderation.warning_variants.begin',AsyncMock(return_value='case')),patch('agent.modules.moderation.warning_variants.finish',AsyncMock()):
        from agent.modules.moderation.warning_variants import build
        await build(value)[command](client,message)
    value.chats.aadd_warning.assert_awaited_once()
    if command == 'swarn':
        message.reply.assert_not_awaited()
        client.delete_messages.assert_not_awaited()
    else:
        client.delete_messages.assert_awaited_once_with(-100,2)


def test_registered_warning_variants():
    assert {'dwarn','swarn'} <= set(moderation.MANIFEST.commands)


@pytest.mark.asyncio
async def test_confirmed_escalation_does_not_claim_false_acknowledgement():
    value = NS(chats=NS(log=lambda *a,**k: None))
    message = NS(chat=NS(id=-100))
    client = NS(ban_chat_member=AsyncMock(return_value=False))
    with patch('agent.modules.moderation.target_is_protected',AsyncMock(return_value=False)):
        text = await moderation.escalate_warning(client,value,message,22,'ban',confirm=True)
    assert 'unconfirmed' in text.lower() and not text.startswith('Threshold reached:')
