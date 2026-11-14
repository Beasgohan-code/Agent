"""Captions, thumbnails and a batch: what is stored is what gets attached.

The point of these tests is that a saved caption is not a saved string — it is
the caption on the next file the bot sends.
"""

import asyncio
from types import SimpleNamespace

from agent.config import Settings
from agent.modules import filestore, renamer
from agent.platform.attachments import (
    CAPTION_KEY,
    THUMB_KEY,
    attachment_kwargs,
    render_caption,
)
from agent.platform.chats import ChatStore
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.storage import Storage
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}

CHAT = 77
USER = 77


class FakeMessage:
    def __init__(self, text="", *, chat_id=CHAT, uid=USER):
        self.text = text
        self.chat = SimpleNamespace(id=chat_id)
        self.id = 100
        self.from_user = SimpleNamespace(id=uid, first_name="Ada")
        self.reply_to_message = None
        self.replies = []
        #: (target, kwargs) for every file this message delivered.
        self.sent = []

    async def reply(self, text, **kwargs):
        self.replies.append(str(text))
        return SimpleNamespace(id=1)

    async def reply_document(self, document=None, **kwargs):
        self.sent.append((str(document), kwargs))
        return SimpleNamespace(id=2)

    async def reply_video(self, video=None, **kwargs):
        self.sent.append((str(video), kwargs))
        return SimpleNamespace(id=3)

    async def reply_cached_media(self, file_id, **kwargs):
        self.sent.append((f"cached:{file_id}", kwargs))
        return SimpleNamespace(id=4)


class FakeClient:
    def __init__(self, messages=(), path=None):
        self._messages = list(messages)
        self._path = path
        self.sent = []
        self.photos = []

    async def get_messages(self, chat_id, message_ids=None):
        return self._messages

    async def send_document(self, chat_id, path, **kwargs):
        self.sent.append((chat_id, path, kwargs))

    async def send_photo(self, chat_id, file_id, caption=None):
        self.photos.append((chat_id, file_id, caption))


def make_ctx(tmp_path):
    settings = Settings.from_env({**ENV, "DATA_DIR": str(tmp_path / "data")})
    ctx = ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        monitor=None,
        chats=ChatStore(tmp_path / "data"),
    )
    return ctx


def run(handler, message, client=None):
    return asyncio.run(handler(client or FakeClient(), message))


# --- the substitution -----------------------------------------------------


def test_a_caption_fills_in_the_name_the_stem_and_the_size():
    text = render_caption("📁 {name} · {size}", name="Show.S01E01.mkv", size="700 MB")
    assert text == "📁 Show.S01E01.mkv · 700 MB"
    assert render_caption("stem {stem}", name="a.b.mkv", size="1 MB") == "stem a.b"
    assert render_caption(None, name="x", size="y") is None


def test_an_unknown_field_stays_visible_instead_of_raising():
    assert render_caption("{name} {nope}", name="a.mkv", size="1 MB") == "a.mkv {nope}"


def test_the_kwargs_are_empty_when_nothing_is_configured(tmp_path):
    chats = ChatStore(tmp_path / "data")
    assert attachment_kwargs(chats, CHAT, name="a.mkv", size="1 MB") == {}
    assert attachment_kwargs(None, CHAT, name="a.mkv", size="1 MB") == {}


# --- the renamer commands -------------------------------------------------


def test_setcaption_then_viewcaption_then_delcaption(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = renamer.build(ctx)

    run(handlers["setcaption"], FakeMessage("/setcaption 📁 {name} · {size}"))
    assert ctx.chats.get(CHAT, CAPTION_KEY) == "📁 {name} · {size}"

    view = FakeMessage("/viewcaption")
    run(handlers["viewcaption"], view)
    assert "Caption for this chat" in view.replies[0]

    run(handlers["delcaption"], FakeMessage("/delcaption"))
    assert ctx.chats.get(CHAT, CAPTION_KEY) is None


def test_a_caption_longer_than_telegrams_cap_is_refused(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = renamer.build(ctx)
    message = FakeMessage("/setcaption " + "x" * 1100)

    run(handlers["setcaption"], message)

    assert "1024" in message.replies[0]
    assert ctx.chats.get(CHAT, CAPTION_KEY) is None


def test_setthumb_stores_the_file_id_and_viewthumb_sends_it_back(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = renamer.build(ctx)
    message = FakeMessage("/setthumb")
    message.reply_to_message = SimpleNamespace(
        photo=SimpleNamespace(file_id="thumb-id"), document=None
    )

    run(handlers["setthumb"], message)
    assert ctx.chats.get(CHAT, THUMB_KEY) == "thumb-id"

    client = FakeClient()
    run(handlers["viewthumb"], FakeMessage("/viewthumb"), client)
    assert client.photos[0][1] == "thumb-id"


def test_setthumb_refuses_a_document_that_is_not_an_image(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = renamer.build(ctx)
    message = FakeMessage("/setthumb")
    message.reply_to_message = SimpleNamespace(
        photo=None, document=SimpleNamespace(file_id="doc", mime_type="application/zip")
    )

    run(handlers["setthumb"], message)

    assert "not an image" in message.replies[0]
    assert ctx.chats.get(CHAT, THUMB_KEY) is None


# --- the attachment is on the file that gets sent -------------------------


def test_get_sends_the_stored_caption_and_thumb(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.chats.put(CHAT, CAPTION_KEY, "{name} ({size})")
    ctx.chats.put(CHAT, THUMB_KEY, "thumb-id")
    source = tmp_path / "sample.mkv"
    source.write_bytes(b"x" * 32)
    stored = ctx.storage.save_path(USER, source, name="sample.mkv", quota_bytes=10_000_000)
    _manifest, handlers = filestore.build(ctx)
    message = FakeMessage(f"/get {stored.id}")

    client = FakeClient()
    run(handlers["get"], message, client)

    # /get now delivers through the message (one path for every store), so the
    # attachment is checked where the file actually leaves the bot.
    path, kwargs = message.sent[0]
    assert kwargs["caption"] == "sample.mkv (32 B)"
    assert kwargs["thumb"] == "thumb-id"
    assert str(path).endswith("sample.mkv")


# --- the batch ------------------------------------------------------------


class BatchItem:
    def __init__(self, message_id, path, name="file.mkv", size=32):
        self.id = message_id
        self.document = SimpleNamespace(file_name=name, file_size=size, mime_type="video/x-matroska")
        self._path = path
        self.downloaded = False

    async def download(self):
        self.downloaded = True
        return self._path


def test_a_batch_saves_the_replied_file_and_the_ones_after_it(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = filestore.build(ctx)
    files = []
    for index in range(3):
        path = tmp_path / f"f{index}.mkv"
        path.write_bytes(bytes([index + 1]) * 16)  # distinct, or the store dedupes
        files.append(BatchItem(100 + index, path, name=f"f{index}.mkv"))
    message = FakeMessage("/batch 3")
    message.reply_to_message = SimpleNamespace(id=100)

    run(handlers["batch"], message, FakeClient(messages=files))

    assert "Batch saved" in message.replies[0]
    assert len(ctx.storage.list_owned(USER)) == 3
    assert all(item.downloaded for item in files)


def test_a_batch_of_messages_without_files_says_so(tmp_path):
    ctx = make_ctx(tmp_path)
    _manifest, handlers = filestore.build(ctx)
    message = FakeMessage("/batch 2")
    message.reply_to_message = SimpleNamespace(id=100)
    plain = [SimpleNamespace(id=100, document=None, photo=None, video=None, audio=None,
                             voice=None, animation=None)]

    run(handlers["batch"], message, FakeClient(messages=plain))

    assert "Nothing saved" in message.replies[0]


def test_check_reports_an_entry_and_a_missing_one(tmp_path):
    ctx = make_ctx(tmp_path)
    source = tmp_path / "a.bin"
    source.write_bytes(b"x" * 8)
    stored = ctx.storage.save_path(USER, source, name="a.bin", quota_bytes=10_000)
    _manifest, handlers = filestore.build(ctx)

    found = FakeMessage(f"/check {stored.id}")
    run(handlers["check"], found)
    assert "Vault entry" in found.replies[0]

    missing = FakeMessage("/check nope")
    run(handlers["check"], missing)
    assert "not in your vault" in missing.replies[0]
