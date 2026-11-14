"""Independent uploads must preserve vault ownership and existing link targets."""
import asyncio

import pytest

from agent.platform.storage import Storage, StoredFile


@pytest.mark.parametrize('method', ['bytes', 'path'])
def test_identical_uploads_never_replace_other_owner_or_existing_record(tmp_path, method):
    store = Storage(tmp_path / 'vault')
    source = tmp_path / 'source'
    source.write_bytes(b'identical')
    def save(owner, name):
        if method == 'bytes':
            return store.save_bytes(owner, name, b'identical')
        return store.save_path(owner, source, name=name)
    first = save(1, 'first.txt')
    first.telegram_file_id = 'existing-cache'
    second = save(2, 'second.txt')
    third = save(1, 'third.txt')
    assert len({first.id, second.id, third.id}) == 3
    assert store.get(first.id).name == 'first.txt'
    assert first.telegram_file_id == 'existing-cache'
    assert store.owner_of(first.id) == 1 and store.owner_of(second.id) == 2
    assert store.usage(1) == 18 and store.usage(2) == 9
    assert not store.delete(first.id, owner_id=2)
    assert store.delete(second.id, owner_id=2)
    assert store.path_for(first).read_bytes() == b'identical'
    assert store.path_for(third).read_bytes() == b'identical'
    loaded = Storage(tmp_path / 'vault')
    assert len(loaded.list_owned(1)) == 2 and not loaded.list_owned(2)


@pytest.mark.parametrize('method', ['bytes', 'path'])
def test_failed_save_removes_only_new_bytes_and_metadata(tmp_path, monkeypatch, method):
    store = Storage(tmp_path / 'vault')
    existing = store.save_bytes(1, 'existing', b'keep')
    def fail():
        raise RuntimeError('save failed')
    monkeypatch.setattr(store, '_save', fail)
    source = tmp_path / 'source'
    source.write_bytes(b'new')
    with pytest.raises(RuntimeError):
        if method == 'bytes':
            store.save_bytes(2, 'new', b'new')
        else:
            store.save_path(2, source)
    assert store.list_owned(2) == []
    assert list(store.files_dir.iterdir()) == [store.path_for(existing)]
    assert source.read_bytes() == b'new'


def test_delete_save_failure_preserves_entry_and_bytes(tmp_path, monkeypatch):
    store = Storage(tmp_path)
    saved = store.save_bytes(1, 'file', b'keep')
    monkeypatch.setattr(store, '_save', lambda: (_ for _ in ()).throw(RuntimeError('save failed')))
    with pytest.raises(RuntimeError):
        store.delete(saved.id, owner_id=1)
    assert store.get(saved.id) is saved
    assert store.path_for(saved).read_bytes() == b'keep'


def test_late_archive_completion_cannot_restore_deleted_file(tmp_path):
    async def scenario():
        store = Storage(tmp_path)
        saved = store.save_bytes(1, 'file', b'keep')
        entered, release = asyncio.Event(), asyncio.Event()
        async def upload(*args):
            entered.set()
            await release.wait()
            return 'cached-id'
        store.attach_archive(upload)
        task = asyncio.create_task(store.archive(saved))
        await entered.wait()
        assert store.delete(saved.id, owner_id=1)
        release.set()
        assert await task == ''
        assert store.get(saved.id) is None
        assert Storage(tmp_path).get(saved.id) is None
    asyncio.run(scenario())


def test_existing_legacy_id_is_not_rewritten(tmp_path):
    store = Storage(tmp_path)
    old = StoredFile('0123456789abcdef', 1, 'legacy', 4, 'oldhash', 1)
    store._index[old.id] = old
    store._ensure_dirs()
    store.path_for(old).write_bytes(b'keep')
    store._save()
    loaded = Storage(tmp_path)
    assert loaded.path_for(loaded.get(old.id)).read_bytes() == b'keep'
    loaded.save_bytes(2, 'new', b'keep')
    assert loaded.get(old.id).owner_id == 1


def test_handle_collision_does_not_replace_metadata(tmp_path, monkeypatch):
    store = Storage(tmp_path)
    saved = store.save_bytes(1, 'file', b'keep')
    monkeypatch.setattr('agent.platform.storage.secrets.token_hex', lambda size: saved.id)
    with pytest.raises(RuntimeError, match='unique storage handle'):
        store.save_bytes(2, 'file', b'other')
    assert store.get(saved.id) is saved
    assert store.path_for(saved).read_bytes() == b'keep'
