"""Quota and digest describe copied bytes, including changing source files."""
import asyncio
import hashlib

import pytest

from agent.platform.storage import Storage, QuotaExceeded


def test_copy_hash_and_size_match_the_actual_bytes(tmp_path):
    store = Storage(tmp_path / 'vault')
    source = tmp_path / 'source'
    content = b'abc' * 200000
    source.write_bytes(content)
    stored = store.save_path(1, source)
    copied = store.path_for(stored).read_bytes()
    assert copied == content
    assert stored.size == len(copied) and stored.sha256 == hashlib.sha256(copied).hexdigest()
    assert store.usage(1) == len(copied)


def test_growth_after_admission_cannot_bypass_quota(tmp_path, monkeypatch):
    store = Storage(tmp_path / 'vault')
    source = tmp_path / 'source'
    source.write_bytes(b'a')
    check = store.check_quota
    calls = 0
    def grow(owner, incoming, **kwargs):
        nonlocal calls
        calls += 1
        check(owner, incoming, **kwargs)
        if calls == 1:
            source.write_bytes(b'x' * 100)
    monkeypatch.setattr(store, 'check_quota', grow)
    with pytest.raises(QuotaExceeded):
        store.save_path(1, source, quota_bytes=10)
    assert not store.list_owned(1)
    assert list(store.files_dir.iterdir()) == []
    assert source.read_bytes() == b'x' * 100


def test_changed_content_hashes_the_version_actually_copied(tmp_path, monkeypatch):
    store = Storage(tmp_path / 'vault')
    source = tmp_path / 'source'
    source.write_bytes(b'old')
    check = store.check_quota
    calls = 0
    def replace(owner, incoming, **kwargs):
        nonlocal calls
        calls += 1
        check(owner, incoming, **kwargs)
        if calls == 1:
            source.write_bytes(b'replacement')
    monkeypatch.setattr(store, 'check_quota', replace)
    saved = store.save_path(1, source)
    assert saved.size == len(b'replacement')
    assert saved.sha256 == hashlib.sha256(b'replacement').hexdigest()
    assert store.path_for(saved).read_bytes() == b'replacement'


def test_midcopy_quota_failure_preserves_preexisting_upload(tmp_path, monkeypatch):
    store = Storage(tmp_path / 'vault')
    existing = store.save_bytes(1, 'keep', b'keep')
    source = tmp_path / 'source'
    source.write_bytes(b'x' * 600000)
    check = store.check_quota
    calls = 0
    def fail_later(owner, incoming, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise QuotaExceeded('quota changed')
        check(owner, incoming, **kwargs)
    monkeypatch.setattr(store, 'check_quota', fail_later)
    with pytest.raises(QuotaExceeded):
        store.save_path(1, source)
    assert store.list_owned(1) == [existing]
    assert list(store.files_dir.iterdir()) == [store.path_for(existing)]
    assert store.path_for(existing).read_bytes() == b'keep'


def test_archive_save_failure_does_not_claim_persisted_cache(tmp_path, monkeypatch):
    async def scenario():
        store = Storage(tmp_path)
        stored = store.save_bytes(1, 'file', b'keep')
        async def archive(*args):
            return 'new-cache-id'
        store.attach_archive(archive)
        def fail():
            raise RuntimeError('save failed')
        monkeypatch.setattr(store, '_save', fail)
        with pytest.raises(RuntimeError):
            await store.archive(stored)
        assert stored.telegram_file_id == ''
        assert store.path_for(stored).read_bytes() == b'keep'
    asyncio.run(scenario())
