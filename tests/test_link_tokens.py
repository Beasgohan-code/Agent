"""Compact independent grants, legacy persistence and missing-state refusal."""
import re
import time

import pytest

from agent.platform.links import LinkStore, LinkRecord, LinkError


def test_new_tokens_fit_telegram_and_hide_identifiers(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'time', lambda: 1234567890)
    store = LinkStore(tmp_path, 'secret')
    first = store.create('private-file-name', 1122334455, max_uses=1)
    second = store.create('private-file-name', 1122334455, max_uses=5)
    assert first.token != second.token
    for record in [first, second]:
        assert re.fullmatch(r'[A-Za-z0-9_-]+', 'link_' + record.token)
        assert len(('link_' + record.token).encode()) <= 64
        assert len(('link:revoke:' + record.token).encode()) <= 64
        assert 'private-file-name' not in record.token
        assert '1122334455' not in record.token
        assert store.verify_signature(record.token)
    store.consume(first.token)
    with pytest.raises(LinkError, match='used up'):
        store.consume(first.token)
    assert second.uses == 0
    store.revoke(first.token, owner_id=1122334455)
    assert not second.revoked


def test_compact_grant_survives_reload(tmp_path):
    store = LinkStore(tmp_path, 'secret')
    record = store.create('file', 1, max_uses=2)
    store.consume(record.token)
    loaded = LinkStore(tmp_path, 'secret')
    assert loaded.resolve(record.token).uses == 1
    loaded.consume(record.token)
    with pytest.raises(LinkError, match='used up'):
        LinkStore(tmp_path, 'secret').resolve(record.token)


@pytest.mark.parametrize('legacy', [False, True])
def test_valid_signature_without_grant_never_restores_unlimited_access(tmp_path, legacy):
    store = LinkStore(tmp_path, 'secret')
    if legacy:
        payload = f'file.1.{int(time.time()) + 3600}'
        token = payload + '.' + store._sign(payload)
    else:
        token = store.create('file', 1, max_uses=1).token
        store._links.clear()
    assert store.verify_signature(token)
    with pytest.raises(LinkError, match='unavailable'):
        store.resolve(token)


def test_indexed_legacy_record_retains_limits_and_revocation(tmp_path):
    store = LinkStore(tmp_path, 'secret')
    now = time.time()
    payload = f'file.1.{int(now) + 3600}'
    token = payload + '.' + store._sign(payload)
    store._links[token] = LinkRecord(token, 'file', 1, now, now + 3600, max_uses=1)
    store._save()
    loaded = LinkStore(tmp_path, 'secret')
    assert loaded.verify_signature(token)
    loaded.consume(token)
    with pytest.raises(LinkError, match='used up'):
        loaded.resolve(token)
    assert loaded.revoke(token, owner_id=1)
    with pytest.raises(LinkError, match='revoked'):
        LinkStore(tmp_path, 'secret').resolve(token)


@pytest.mark.parametrize('token', ['é', 'x'*5000, 'v2_invalid', 'a.b.c.é'])
def test_untrusted_token_shapes_fail_safely(tmp_path, token):
    store = LinkStore(tmp_path, 'secret')
    assert not store.verify_signature(token)
    with pytest.raises(LinkError):
        store.resolve(token)


@pytest.mark.parametrize('operation', ['create', 'consume', 'revoke'])
def test_immediate_persistence_failure_does_not_leave_applied_memory_state(tmp_path, monkeypatch, operation):
    store = LinkStore(tmp_path, 'secret')
    record = store.create('file', 1, max_uses=2)
    def fail():
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(store, '_save', fail)
    with pytest.raises(RuntimeError, match='database unavailable'):
        if operation == 'create':
            store.create('another', 1)
        elif operation == 'consume':
            store.consume(record.token)
        else:
            store.revoke(record.token, owner_id=1)
    assert len(store.owned(1)) == 1
    assert record.uses == 0 and not record.revoked
