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
