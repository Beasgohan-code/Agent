"""Log diagnostics distinguish local recording from Telegram delivery."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.platform.logbook import LogBook


@pytest.mark.asyncio
async def test_log_delivery_status_success_failure_and_no_retry(tmp_path):
    book=LogBook(tmp_path,owner_id=11)
    assert book.delivery_status()['last_result']=='not attempted'
    book.client=NS(send_message=AsyncMock(return_value=NS(id=1)))
    assert await book.post('start',version='test')
    assert book.delivery_status()['sent']==1
    book.client.send_message=AsyncMock(side_effect=RuntimeError('PRIVATE_TOKEN'))
    assert not await book.post('start')
    status=book.delivery_status()
    assert status['failed']==1 and status['last_result']=='failed'
    assert status['error_type']=='RuntimeError' and 'PRIVATE_TOKEN' not in str(status)
    book.client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_suppression_distinguishes_missing_client_destination_and_hydration(tmp_path):
    book=LogBook(tmp_path)
    assert not await book.post('start')
    assert book.delivery_status()['last_result']=='no destination'
    book.owner_id=11
    assert not await book.post('start')
    assert book.delivery_status()['last_result']=='client unavailable'
    book._config_loaded=False
    assert not await book.post('start')
    assert book.delivery_status()['last_result']=='settings not loaded'


@pytest.mark.asyncio
async def test_owner_log_test_reports_actual_send_and_nonowner_cannot_send(tmp_path):
    from test_logbook import make_ctx,FakeClient,FakeMessage
    from agent.modules import ops
    client=FakeClient()
    ctx=make_ctx(tmp_path,client)
    handler=ops.build(ctx)[1]['log']
    message=FakeMessage('/log test',uid=11)
    await handler(client,message)
    assert 'delivered' in str(message.replies[-1])
    sent=len(client.sent)
    await handler(client,FakeMessage('/log test',uid=999))
    assert len(client.sent)==sent


@pytest.mark.asyncio
async def test_startup_failure_not_hidden_by_later_success(tmp_path):
    from pyrogram.errors import ChatWriteForbidden
    book=LogBook(tmp_path,owner_id=11)
    book.client=NS(send_message=AsyncMock(side_effect=[ChatWriteForbidden(),NS(id=2)]))
    assert not await book.post('start')
    assert await book.post('new_user',uid=22)
    status=book.delivery_status()
    assert status['last_result']=='sent'
    assert status['startup']['last_result']=='failed'
    assert 'posting' in status['startup']['hint'].lower()


@pytest.mark.asyncio
async def test_real_start_event_bridge_posts_exactly_once(tmp_path):
    from agent.platform.events import EventLog
    from agent.platform.logbook import subscribe
    book=LogBook(tmp_path,owner_id=11)
    book.client=NS(send_message=AsyncMock(return_value=NS(id=123)))
    client=book.client
    events=EventLog()
    subscribe(events,book)
    events.emit('start',version='test')
    await book.close(timeout=1)
    client.send_message.assert_awaited_once()
    assert '#BotStarted' in client.send_message.await_args.args[1]
    assert book.delivery_status()['startup']['last_result']=='sent'


@pytest.mark.asyncio
@pytest.mark.parametrize('result',[None,False,NS(id=0)])
async def test_unacknowledged_log_not_reported_as_delivered(tmp_path,result):
    book=LogBook(tmp_path,owner_id=11)
    book.client=NS(send_message=AsyncMock(return_value=result))
    assert not await book.post('start')
    assert book.delivery_status()['sent']==0
