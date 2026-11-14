"""Vault durability: the index survives a redeploy, the bytes can live in Telegram.

A container's filesystem is wiped on every deploy, so "the file is on disk" is
not durability. Two mechanisms fix that, and each is checked here on its own:
the index is a scoped PostgreSQL document, and the bytes can be archived to a
storage channel whose ``file_id`` outlives any host.
"""

import asyncio

from agent.platform.storage import Storage
from agent.utils import delivery


class FakeDB:
    connected = True

    def __init__(self):
        self.docs = {}
        self.saved = 0

    def get(self, name, default=None):
        return self.docs.get(name, default)

    def has(self, name):
        return name in self.docs

    def save(self, name, value):
        self.docs[name] = value
        self.saved += 1


class FakeMessage:
    def __init__(self):
        self.replies = []
        self.sent = []

    async def reply(self, text, **kwargs):
        self.replies.append(str(text))

    async def reply_document(self, document=None, file_name=None, caption=None, **kwargs):
        self.sent.append(("document", str(document), file_name, caption, kwargs))

    async def reply_video(self, video=None, file_name=None, caption=None, **kwargs):
        self.sent.append(("video", str(video), file_name, caption, kwargs))

    async def reply_cached_media(self, file_id, caption=None, **kwargs):
        self.sent.append(("cached", file_id, None, caption, kwargs))


def write(tmp_path, name="clip.mkv", size=64):
    path = tmp_path / name
    path.write_bytes(b"z" * size)
    return path


# --- the index -------------------------------------------------------------


def test_the_index_is_written_to_the_database(tmp_path):
    db = FakeDB()
    store = Storage(tmp_path, db=db)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")

    assert "files" in db.docs
    assert db.docs["files"][stored.id]["name"] == "clip.mkv"
    assert db.docs["files"][stored.id]["owner_id"] == 11


def test_a_new_process_finds_the_files_through_the_database(tmp_path):
    db = FakeDB()
    first = Storage(tmp_path, db=db)
    stored = first.save_path(11, write(tmp_path), name="clip.mkv")

    # A redeploy: same database, empty host.
    second = Storage(tmp_path, db=db)

    assert second.get(stored.id) is not None
    assert second.owner_of(stored.id) == 11
    assert second.usage(11) == stored.size


def test_hydrate_rereads_the_index_after_the_database_is_loaded(tmp_path):
    db = FakeDB()
    store = Storage(tmp_path, db=db)          # built before the DB is readable
    assert store.list_owned(11) == []

    from agent.platform.db import save_document

    save_document(db, "files", tmp_path / "index.json", {
        "abc": {
            "id": "abc", "owner_id": 11, "name": "later.mkv",
            "size": 5, "sha256": "x", "created_at": 1.0,
        }
    })
    store.hydrate()

    assert store.get("abc").name == "later.mkv"


# --- archiving -------------------------------------------------------------


def test_a_stored_file_is_archived_and_its_file_id_remembered(tmp_path):
    uploaded = []

    async def uploader(path, name):
        uploaded.append((str(path), name))
        return "BQACAgQAAx"

    store = Storage(tmp_path)
    store.attach_archive(uploader)

    stored = store.save_path(11, write(tmp_path), name="clip.mkv")
    asyncio.run(store.archive(stored))

    assert uploaded and uploaded[0][1] == "clip.mkv"
    assert store.get(stored.id).telegram_file_id == "BQACAgQAAx"


def test_archiving_is_idempotent(tmp_path):
    calls = []

    async def uploader(path, name):
        calls.append(name)
        return "file-id"

    store = Storage(tmp_path)
    store.attach_archive(uploader)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")

    asyncio.run(store.archive(stored))
    asyncio.run(store.archive(store.get(stored.id)))

    assert calls == ["clip.mkv"]              # uploaded once, not twice


def test_a_failed_archive_keeps_the_file_on_disk(tmp_path):
    async def uploader(path, name):
        raise RuntimeError("channel is gone")

    store = Storage(tmp_path)
    store.attach_archive(uploader)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")

    assert asyncio.run(store.archive(stored)) == ""
    assert store.path_for(stored).exists()
    assert store.get(stored.id).telegram_file_id == ""


def test_without_a_channel_nothing_is_archived(tmp_path):
    store = Storage(tmp_path)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")

    assert store.archiving is False
    assert asyncio.run(store.archive(stored)) == ""


# --- delivery --------------------------------------------------------------


def test_delivery_prefers_the_telegram_file_id(tmp_path):
    store = Storage(tmp_path)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")
    stored.telegram_file_id = "BQACAgQAAx"
    message = FakeMessage()

    assert asyncio.run(delivery.send_stored(message, store, stored)) is True

    kind, target, _name, _caption, _kwargs = message.sent[0]
    assert kind == "cached" and target == "BQACAgQAAx"


def test_a_stale_file_id_falls_back_to_the_disk(tmp_path):
    store = Storage(tmp_path)
    stored = store.save_path(11, write(tmp_path), name="clip.mkv")
    stored.telegram_file_id = "stale"

    class Refusing(FakeMessage):
        async def reply_cached_media(self, file_id, **kwargs):
            raise RuntimeError("FILE_ID_INVALID")

    message = Refusing()

    assert asyncio.run(delivery.send_stored(message, store, stored)) is True
    assert message.sent[0][0] == "video"       # mkv plays inline


def test_a_file_with_no_bytes_anywhere_says_so(tmp_path):
    store = Storage(tmp_path)
    stored = store.save_bytes(11, "gone.bin", b"1234")
    store.path_for(stored).unlink()
    message = FakeMessage()

    assert asyncio.run(delivery.send_stored(message, store, stored)) is False
    assert "bytes are gone" in message.replies[0]


def test_the_caption_reaches_the_file(tmp_path):
    store = Storage(tmp_path)
    stored = store.save_bytes(11, "doc.pdf", b"1234")
    message = FakeMessage()

    asyncio.run(delivery.send_stored(message, store, stored, caption="hello"))

    assert message.sent[0][3] == "hello"


def test_the_storage_channel_is_configurable():
    from agent.config import Settings

    env = {
        "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
        "API_ID": "1234567",
        "API_HASH": "0123456789abcdef0123456789abcdef",
    }

    assert Settings.from_env(env).storage_channel is None
    assert Settings.from_env({**env, "STORAGE_CHANNEL": "-1001234567890"}).storage_channel == -1001234567890
