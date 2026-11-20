from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from pyrogram.enums import ChatType, ChatMemberStatus
from agent.modules import moderation


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['dwarn','swarn'])
@pytest.mark.parametrize('hydrate',[False,True])
async def test_warning_variant_admission_and_silence(command,hydrate):
    value = NS(settings=NS(owner_id=11),chats=NS(aadd_warning=AsyncMock(return_value=1),log=lambda *a,**k: None))
    message = NS(id=10,text='/'+command,chat=NS(id=-100,type=ChatType.SUPERGROUP),from_user=NS(id=11),reply_to_message=NS(id=2,chat=NS(id=-100),from_user=NS(id=22)),reply=AsyncMock())
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,privileges=NS(can_restrict_members=True,can_delete_messages=True))),delete_messages=AsyncMock(return_value=True))
    if hydrate:
        client.get_messages=AsyncMock(return_value=message.reply_to_message)
        message.reply_to_message=None
        message.reply_to_message_id=2
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(3,'mute'))), patch('agent.modules.moderation.warning_variants.begin',AsyncMock(return_value='case')),patch('agent.modules.moderation.warning_variants.finish',AsyncMock()):
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


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError])
@pytest.mark.parametrize('command,partial', [('dwarn', False), ('dwarn', True), ('swarn', True)])
async def test_confirmed_warning_delivery_failure_does_not_rewrite_outcome_or_resend(failure, command, partial, caplog):
    value = NS(chats=NS(aadd_warning=AsyncMock(return_value=1), log=lambda *a, **k: None))
    message = NS(id=10, text='/' + command, chat=NS(id=-100, type=ChatType.SUPERGROUP),
        from_user=NS(id=11), reply_to_message=NS(id=2, chat=NS(id=-100), from_user=NS(id=22)),
        reply=AsyncMock(side_effect=[failure('SECRET_DELIVERY_TEXT'), None]))
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),
        get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
            privileges=NS(can_restrict_members=True, can_delete_messages=True))),
        delete_messages=AsyncMock(return_value=True))
    finish = AsyncMock()
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(1 if partial else 3, 'mute'))), \
         patch('agent.modules.moderation.escalate_warning', AsyncMock(return_value='Escalation unconfirmed')), \
         patch('agent.modules.moderation.warning_variants.begin', AsyncMock(return_value='case')), \
         patch('agent.modules.moderation.warning_variants.finish', finish):
        from agent.modules.moderation.warning_variants import build
        await build(value)[command](client, message)
    finish.assert_awaited_once_with(value, 'case', 'partial' if partial else 'applied')
    message.reply.assert_awaited_once()
    value.chats.aadd_warning.assert_awaited_once()
    if command == 'dwarn':
        client.delete_messages.assert_awaited_once_with(-100, 2)
    else:
        client.delete_messages.assert_not_awaited()
    assert 'SECRET_DELIVERY_TEXT' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['delivery', 'cleanup'])
async def test_warning_delivery_cancellation_keeps_confirmed_outcome(stage):
    import asyncio
    value = NS(chats=NS(aadd_warning=AsyncMock(return_value=1), log=lambda *a, **k: None))
    message = NS(id=10, text='/dwarn', chat=NS(id=-100, type=ChatType.SUPERGROUP),
        from_user=NS(id=11), reply_to_message=NS(id=2, chat=NS(id=-100), from_user=NS(id=22)),
        reply=AsyncMock(side_effect=asyncio.CancelledError if stage == 'delivery' else None))
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),
        get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
            privileges=NS(can_restrict_members=True, can_delete_messages=True))),
        delete_messages=AsyncMock(return_value=True, side_effect=asyncio.CancelledError if stage == 'cleanup' else None))
    finish = AsyncMock()
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(3, 'mute'))), \
         patch('agent.modules.moderation.warning_variants.begin', AsyncMock(return_value='case')), \
         patch('agent.modules.moderation.warning_variants.finish', finish):
        from agent.modules.moderation.warning_variants import build
        with pytest.raises(asyncio.CancelledError):
            await build(value)['dwarn'](client, message)
    if stage == 'delivery':
        finish.assert_awaited_once_with(value, 'case', 'applied')
        message.reply.assert_awaited_once()
    else:
        finish.assert_not_awaited()
        message.reply.assert_not_awaited()
    value.chats.aadd_warning.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError, 'blocked'])
async def test_delete_warning_cleanup_failure_records_partial_without_replay(failure, caplog, monkeypatch):
    import asyncio
    stopped = asyncio.Event()
    async def blocked(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    original = asyncio.wait_for
    async def fast_timeout(awaitable, timeout):
        assert timeout == 10
        return await original(awaitable, timeout=0.01)
    if failure == 'blocked':
        monkeypatch.setattr(asyncio, 'wait_for', fast_timeout)
    value = NS(chats=NS(aadd_warning=AsyncMock(return_value=1), log=lambda *a, **k: None))
    message = NS(id=10, text='/dwarn', chat=NS(id=-100, type=ChatType.SUPERGROUP),
        from_user=NS(id=11), reply_to_message=NS(id=2, chat=NS(id=-100), from_user=NS(id=22)),
        reply=AsyncMock())
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),
        get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
            privileges=NS(can_restrict_members=True, can_delete_messages=True))),
        delete_messages=AsyncMock(side_effect=blocked if failure == 'blocked' else failure('SECRET_CLEANUP_TEXT')))
    finish = AsyncMock()
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(3, 'mute'))), \
         patch('agent.modules.moderation.warning_variants.begin', AsyncMock(return_value='case')), \
         patch('agent.modules.moderation.warning_variants.finish', finish):
        from agent.modules.moderation.warning_variants import build
        await build(value)['dwarn'](client, message)
    finish.assert_awaited_once_with(value, 'case', 'partial')
    value.chats.aadd_warning.assert_awaited_once()
    client.delete_messages.assert_awaited_once_with(-100, 2)
    message.reply.assert_awaited_once()
    body = str(message.reply.await_args.args[0])
    assert 'Warning recorded' in body and 'Cleanup or escalation unconfirmed' in body
    assert 'SECRET_CLEANUP_TEXT' not in body + caplog.text
    if failure == 'blocked':
        assert stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['dwarn', 'swarn'])
async def test_local_audit_failure_does_not_skip_warning_escalation_or_cleanup(command, caplog):
    from unittest.mock import Mock
    value = NS(chats=NS(aadd_warning=AsyncMock(return_value=3),
        log=Mock(side_effect=RuntimeError('SECRET_AUDIT_TEXT'))))
    message = NS(id=10, text='/' + command, chat=NS(id=-100, type=ChatType.SUPERGROUP),
        from_user=NS(id=11), reply_to_message=NS(id=2, chat=NS(id=-100), from_user=NS(id=22)),
        reply=AsyncMock())
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),
        get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
            privileges=NS(can_restrict_members=True, can_delete_messages=True))),
        delete_messages=AsyncMock(return_value=True))
    finish = AsyncMock()
    escalate = AsyncMock(return_value='Threshold reached: muted.')
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(3, 'mute'))), \
         patch('agent.modules.moderation.escalate_warning', escalate), \
         patch('agent.modules.moderation.warning_variants.begin', AsyncMock(return_value='case')), \
         patch('agent.modules.moderation.warning_variants.finish', finish):
        from agent.modules.moderation.warning_variants import build
        await build(value)[command](client, message)
    escalate.assert_awaited_once_with(client, value, message, 22, 'mute', confirm=True)
    finish.assert_awaited_once_with(value, 'case', 'partial')
    value.chats.aadd_warning.assert_awaited_once()
    if command == 'dwarn':
        client.delete_messages.assert_awaited_once_with(-100, 2)
    else:
        client.delete_messages.assert_not_awaited()
    message.reply.assert_awaited_once()
    body = str(message.reply.await_args.args[0])
    assert 'Warning recorded' in body and 'Local audit unconfirmed' in body
    assert 'Cleanup or escalation unconfirmed' not in body
    assert 'SECRET_AUDIT_TEXT' not in body + caplog.text
