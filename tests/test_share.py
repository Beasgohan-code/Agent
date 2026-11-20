"""The share-link workflow end to end: create → deep link → redeem → control."""

import asyncio
import subprocess

import pytest

from agent.config import Settings
from agent.modules import encoder, linkshare
from agent.platform.context import ModuleContext
from agent.platform.deeplinks import DeepLinkRouter
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkStore
from agent.platform.storage import Storage
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


class FakeMessage:
    sequence = 0

    def __init__(self, text="", *, reply_to=None, uid=11):
        type(self).sequence += 1
        self.id = type(self).sequence
        from types import SimpleNamespace
        self.chat = SimpleNamespace(id=uid)
        self.text = text
        self.reply_to_message = reply_to
        self.from_user = FakeUser(uid)
        self.replies = []
        self.files = []

    async def reply(self, text, **_kwargs):
        self.replies.append(text)

    async def reply_document(self, document=None, caption=None, **_kwargs):
        self.files.append(("document", str(document), caption or ""))

    async def reply_video(self, video=None, caption=None, **_kwargs):
        self.files.append(("video", str(video), caption or ""))


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeMedia:
    def __init__(self, path, name="clip.mp4"):
        self.file_name = name
        self.path = path


class FakeReply:
    def __init__(self, media):
        self.document = media
        self.video = None

    async def download(self):
        return str(self.document.path)


class FakeClient:
    def __init__(self, username="agent_bot"):
        self.me = type("Me", (), {"username": username})()


@pytest.fixture()
def media(tmp_path):
    target = tmp_path / "clip.mp4"
    subprocess.run(
        [encoder.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=96x64:rate=8",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)],
        check=True, timeout=120,
    )
    return target


@pytest.fixture()
def ctx(tmp_path):
    return ModuleContext(
        settings=Settings.from_env(ENV),
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "test-secret"),
        deeplinks=DeepLinkRouter(),
    )


def run(coro):
    return asyncio.run(coro)


def share(ctx, media, command="/genlink 6"):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage(command, reply_to=FakeReply(FakeMedia(media)))
    run(handlers["genlink"](FakeClient(), message))
    return message


def token_of(reply_text: str) -> str:
    """The token inside ``?start=link_<token>``."""
    marker = "start=link_"
    start = reply_text.index(marker) + len(marker)
    end = start
    while end < len(reply_text) and not reply_text[end].isspace() and reply_text[end] not in "<&":
        end += 1
    return reply_text[start:end]


def test_the_card_carries_a_clickable_deep_link():
    # no bot at hand: a card built from a username alone is enough to check the URL
    from agent.modules.linkshare import _link_url

    assert _link_url("agent_bot", "abc.def") == "https://t.me/agent_bot?start=link_abc.def"
    assert _link_url("", "abc.def") == ""


def test_a_share_card_shows_the_file_and_its_limits(ctx, media):
    message = share(ctx, media, "/genlink 6 3")

    text = message.replies[0]
    assert "Share link" in text
    assert "clip.mp4" in text
    assert "3 of 3 left" in text
    assert "t.me/agent_bot?start=link_" in text


def test_the_deep_link_hands_the_file_over(ctx, media):
    message = share(ctx, media)
    token = token_of(message.replies[0])

    # the module registered its prefix on the router the bot handed it
    assert ctx.deeplinks.handles(f"link_{token}")
    opened = FakeMessage(f"/start link_{token}")
    run(ctx.deeplinks.dispatch(None, opened, f"link_{token}"))

    assert opened.files, opened.replies
    kind, path, caption = opened.files[0]
    assert kind == "video"                     # mp4 goes out playable
    assert path.endswith("clip.mp4")
    assert "clip.mp4" in caption.replace("&amp;", "&")

    record = ctx.links.get(token)
    assert record.uses == 1


def test_a_link_stops_working_once_its_uses_are_gone(ctx, media):
    message = share(ctx, media, "/genlink 6 1")
    token = token_of(message.replies[0])

    run(ctx.deeplinks.dispatch(None, FakeMessage(f"/start link_{token}"), f"link_{token}"))
    second = FakeMessage(f"/start link_{token}")
    run(ctx.deeplinks.dispatch(None, second, f"link_{token}"))

    assert second.files == []
    assert "Link unavailable" in second.replies[0]
    assert "as often as it allows" in second.replies[0]


def test_a_revoked_link_says_so(ctx, media):
    message = share(ctx, media)
    token = token_of(message.replies[0])
    ctx.links.revoke(token, owner_id=11)

    opened = FakeMessage(f"/start link_{token}")
    run(ctx.deeplinks.dispatch(None, opened, f"link_{token}"))

    assert opened.files == []
    assert "revoked" in opened.replies[0]


def test_an_expired_link_says_so(ctx, media):
    message = share(ctx, media, "/genlink 1")
    token = token_of(message.replies[0])
    ctx.links.get(token).expires_at = 0.0

    opened = FakeMessage(f"/start link_{token}")
    run(ctx.deeplinks.dispatch(None, opened, f"link_{token}"))

    assert opened.files == []
    assert "expired" in opened.replies[0]


def test_a_file_that_vanished_is_reported_not_crashed(ctx, media):
    message = share(ctx, media)
    token = token_of(message.replies[0])
    record = ctx.links.get(token)
    ctx.storage.delete(record.file_id, owner_id=11)

    opened = FakeMessage(f"/start link_{token}")
    run(ctx.deeplinks.dispatch(None, opened, f"link_{token}"))

    assert opened.files == []
    assert "no longer stored" in opened.replies[0]
    assert record.uses == 0  # Missing metadata must not spend a redemption.


def test_a_vault_file_is_shared_without_storing_it_twice(ctx, media):
    _, handlers = linkshare.build(ctx)
    stored = ctx.storage.save_path(11, media, name="clip.mp4")

    message = FakeMessage(f"/share {stored.id} 6 2")
    run(handlers["share"](FakeClient(), message))

    text = message.replies[0]
    assert "Share link" in text
    assert "2 of 2 left" in text
    token = token_of(text)
    assert ctx.links.get(token).file_id == stored.id
    # sharing a stored file must not duplicate it in the vault
    assert len(ctx.storage.list_owned(11)) == 1


def test_sharing_somebody_elses_file_is_refused(ctx, media):
    _, handlers = linkshare.build(ctx)
    stored = ctx.storage.save_path(99, media, name="theirs.mp4")

    message = FakeMessage(f"/share {stored.id}")
    run(handlers["share"](FakeClient(), message))

    assert "No file with that id" in message.replies[0]


def test_share_without_an_id_lists_the_vault(ctx, media):
    _, handlers = linkshare.build(ctx)
    ctx.storage.save_path(11, media, name="clip.mp4")

    message = FakeMessage("/share")
    run(handlers["share"](FakeClient(), message))

    assert "Share a stored file" in message.replies[0]
    assert "clip.mp4" in message.replies[0]


def test_a_forged_token_is_refused(ctx):
    linkshare.build(ctx)          # registers the ``link`` prefix on the router
    opened = FakeMessage("/start link_forged")
    run(ctx.deeplinks.dispatch(None, opened, "link_forged"))

    assert opened.files == []
    assert "not valid" in opened.replies[0]
