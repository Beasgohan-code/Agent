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
        assert timeout in (5, 10)
        return await original(awaitable, timeout=0.01 if timeout == 10 else timeout)
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


@pytest.fixture
def warning_case():
    value = NS(chats=NS(aadd_warning=AsyncMock(return_value=1), log=lambda *a, **k: None))
    message = NS(id=10, text='/dwarn', chat=NS(id=-100, type=ChatType.SUPERGROUP),
        from_user=NS(id=11), reply_to_message=NS(id=2, chat=NS(id=-100), from_user=NS(id=22)),
        reply=AsyncMock())
    client = NS(get_me=AsyncMock(return_value=NS(id=99)),
        get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
            privileges=NS(can_restrict_members=True, can_delete_messages=True))),
        delete_messages=AsyncMock(return_value=True))
    return value, message, client


@pytest.mark.asyncio
@pytest.mark.parametrize('command,revoked', [('dwarn', 'can_delete_messages'),
    ('dwarn', 'can_restrict_members'), ('swarn', 'can_restrict_members')])
async def test_warning_variants_reauthorize_after_threshold_read(warning_case, command, revoked):
    value, message, client = warning_case
    message.text = '/' + command
    changed = False
    async def threshold(*args):
        nonlocal changed
        changed = True
        return 3, 'mute'
    async def authority(*args, need=None, **kwargs):
        return not (changed and need == revoked)
    begin = AsyncMock(return_value='case')
    with patch('agent.modules.moderation.is_moderator', AsyncMock(side_effect=authority)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', threshold), \
         patch('agent.modules.moderation.warning_variants.begin', begin):
        from agent.modules.moderation.warning_variants import build
        await build(value)[command](client, message)
    begin.assert_not_awaited()
    value.chats.aadd_warning.assert_not_awaited()
    client.delete_messages.assert_not_awaited()
    assert 'permissions changed' in str(message.reply.await_args.args[0]).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['dwarn', 'swarn'])
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError, 'case'])
async def test_final_warning_outcome_failure_keeps_confirmed_warning_and_does_not_retry(warning_case, command, failure, caplog):
    from agent.platform.restriction_cases import CaseError
    value, message, client = warning_case
    message.text = '/' + command
    error = (CaseError if failure == 'case' else failure)('SECRET_OUTCOME_TEXT')
    finish = AsyncMock(side_effect=error)
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', AsyncMock(return_value=(3, 'mute'))), \
         patch('agent.modules.moderation.warning_variants.begin', AsyncMock(return_value='case')), \
         patch('agent.modules.moderation.warning_variants.finish', finish):
        from agent.modules.moderation.warning_variants import build
        await build(value)[command](client, message)
    finish.assert_awaited_once_with(value, 'case', 'applied')
    value.chats.aadd_warning.assert_awaited_once()
    message.reply.assert_awaited_once()
    body = str(message.reply.await_args.args[0])
    assert 'Warning recorded' in body and 'Outcome recording unconfirmed' in body
    assert 'SECRET_OUTCOME_TEXT' not in body + caplog.text
    if command == 'dwarn':
        client.delete_messages.assert_awaited_once_with(-100, 2)
    else:
        client.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['before_commit', 'after_commit', 'cancel_after_commit'])
async def test_warning_outcome_uncertainty_with_independent_storage_connections(tmp_path, warning_case, boundary):
    import asyncio
    import os
    import uuid
    from agent.platform.db import Database
    from agent.platform.chats import ChatStore
    from agent.platform import restriction_cases
    from agent.modules.moderation import warning_variants
    url = os.environ.get('AGENT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable database required')
    scope = 'warning-outcome:' + uuid.uuid4().hex
    writer = Database(url, scope=scope, required=True)
    reader = Database(url, scope=scope, required=True)
    value, message, client = warning_case
    try:
        assert await writer.connect()
        assert await reader.connect()
        await writer.load()
        await reader.load()
        value.db = writer
        value.chats = ChatStore(tmp_path / 'writer', db=writer)
        observer = ChatStore(tmp_path / 'reader', db=reader)
        async def uncertain_finish(ctx, identity, outcome):
            if boundary != 'before_commit':
                await restriction_cases.finish(ctx, identity, outcome)
            if boundary == 'cancel_after_commit':
                raise asyncio.CancelledError()
            raise TimeoutError('SECRET_STORAGE_ACK')
        finish = AsyncMock(side_effect=uncertain_finish)
        with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
             patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
             patch.object(warning_variants, 'warning_threshold', AsyncMock(return_value=(3, 'mute'))), \
             patch.object(warning_variants, 'finish', finish):
            handler = warning_variants.build(value)['dwarn']
            if boundary == 'cancel_after_commit':
                with pytest.raises(asyncio.CancelledError):
                    await handler(client, message)
                message.reply.assert_not_awaited()
            else:
                await handler(client, message)
                assert 'Warning recorded' in str(message.reply.await_args.args[0])
            finish.assert_awaited_once()
            assert await observer.aactive_warning_count(-100, 22) == 1
            history = await restriction_cases.history(NS(db=reader), -100)
            expected = 'pending' if boundary == 'before_commit' else 'applied'
            assert len(history) == 1 and history[0]['action'] == 'dwarn:' + expected
            # Redelivery is stopped by real durable admission, not a mock.
            await handler(client, message)
            finish.assert_awaited_once()
            assert await observer.aactive_warning_count(-100, 22) == 1
            client.delete_messages.assert_awaited_once_with(-100, 2)
            async with reader._pool.acquire() as conn:
                assert await conn.fetchval('SELECT count(*) FROM agent_restriction_cases WHERE tenant=$1 AND chat_id=$2', scope + ':other', -100) == 0
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['identity', 'threshold'])
async def test_warning_preaction_reads_have_deadlines_without_admission(warning_case, stage, monkeypatch, caplog):
    import asyncio
    value, message, client = warning_case
    stopped = asyncio.Event()
    async def blocked(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    threshold = AsyncMock(return_value=(3, 'mute'))
    if stage == 'identity':
        client.get_me = AsyncMock(side_effect=blocked)
    else:
        threshold.side_effect = blocked
    original = asyncio.wait_for
    async def fast_timeout(awaitable, timeout):
        assert timeout == 5
        return await original(awaitable, timeout=0.01)
    monkeypatch.setattr(asyncio, 'wait_for', fast_timeout)
    begin = AsyncMock(return_value='case')
    with patch('agent.modules.moderation.is_moderator', AsyncMock(return_value=True)), \
         patch('agent.modules.moderation.target_is_protected', AsyncMock(return_value=False)), \
         patch('agent.modules.moderation.warning_variants.warning_threshold', threshold), \
         patch('agent.modules.moderation.warning_variants.begin', begin):
        from agent.modules.moderation.warning_variants import build
        await original(build(value)['dwarn'](client, message), timeout=0.2)
    assert stopped.is_set()
    begin.assert_not_awaited()
    value.chats.aadd_warning.assert_not_awaited()
    client.delete_messages.assert_not_awaited()
    message.reply.assert_awaited_once()
