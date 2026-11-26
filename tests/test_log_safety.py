"""Searchable logs must be bounded and minimize credentials/content on every sink."""
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from agent.platform.logbook import format_event,tag_for,LogBook
from agent.platform.events import EventLog

TOKEN='123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi'


def test_structured_log_redacts_nested_credentials_and_content():
    text=format_event('error',{'bot_token':TOKEN,'metadata':{'password':'PRIVATE_PASSWORD','session_string':'PRIVATE_SESSION'},'message_text':'PRIVATE_MESSAGE','error':ValueError('PRIVATE_EXCEPTION'),'incident':'abc123'})
    assert not any(secret in text for secret in (TOKEN,'PRIVATE_PASSWORD','PRIVATE_SESSION','PRIVATE_MESSAGE','PRIVATE_EXCEPTION'))
    assert 'abc123' in text and 'ValueError' in text


def test_unlabelled_common_credentials_redacted_and_html_safe():
    text=format_event('error',{'detail':f'{TOKEN} postgres://alice:PRIVATE_PASSWORD@db/app <script>'})
    assert TOKEN not in text and 'PRIVATE_PASSWORD' not in text
    assert '<script>' not in text and '&lt;script&gt;' in text


def test_hashtag_cannot_inject_html_or_secondary_tags():
    tag=tag_for('bad <tag> #Injected\n'+'x'*500)
    assert len(tag)<=48 and tag.isascii() and tag.isalnum()
    assert format_event('new_user',{},when=0).find('1970-01-01')>=0


def test_event_cards_bounded_even_after_html_escaping():
    text=format_event('error',{('x'*100+str(i)):'<&'*10000 for i in range(100)})
    assert len(text)<=4000
    assert 'omitted' in text.lower() or 'truncated' in text.lower()


def test_event_ring_and_listeners_never_receive_raw_secrets(caplog):
    events=EventLog()
    received=[]
    events.subscribe(lambda kind,fields:received.append(fields))
    with caplog.at_level(logging.INFO,logger='agent.events'):
        events.emit('error',token=TOKEN,detail='password=PRIVATE_PASSWORD',incident='abc')
    assert TOKEN not in caplog.text and 'PRIVATE_PASSWORD' not in caplog.text
    assert TOKEN not in str(events.recent()) and TOKEN not in str(received)
    assert events.recent(limit=0)==[]


@pytest.mark.asyncio
async def test_no_destination_console_fallback_does_not_leak(caplog,tmp_path):
    book=LogBook(tmp_path)
    with caplog.at_level(logging.INFO):
        assert not await book.post('error',token=TOKEN)
    assert TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_send_failure_logs_no_raw_provider_error_or_retry(caplog,tmp_path):
    book=LogBook(tmp_path,owner_id=11)
    book.client=NS(send_message=AsyncMock(side_effect=RuntimeError('PRIVATE_EXCEPTION '+TOKEN)))
    with caplog.at_level(logging.WARNING):
        assert not await book.post('error',incident='abc')
    assert TOKEN not in caplog.text and 'PRIVATE_EXCEPTION' not in caplog.text
    assert '#Errors' in caplog.text and book.client.send_message.await_count==1


def test_event_copies_and_reserved_metadata_cannot_be_overwritten():
    events=EventLog()
    events.subscribe(lambda kind,fields:fields['metadata'].update(incident='changed'))
    result=events.emit('error',metadata={'incident':'original'},at='forged timestamp')
    assert result['metadata']['incident']=='original'
    assert isinstance(result['at'],float)
    result['metadata']['incident']='changed again'
    assert events.recent()[0]['metadata']['incident']=='original'


def test_error_card_keeps_incident_and_severity_searchable():
    text=format_event('error',{'incident':'abc123','error_type':'TimeoutError','occurrences':12,'saved':True},when=0)
    assert '<b>#Errors</b>' in text and 'ERROR' in text
    assert 'abc123' in text and 'TimeoutError' in text and '12' in text
