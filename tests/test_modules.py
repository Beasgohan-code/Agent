"""Module handlers driven by fake Telegram messages."""

import asyncio
import re
import subprocess
from types import SimpleNamespace

import pytest

from agent.modules import encoder, linkshare
from agent.platform.context import ModuleContext
from agent.platform.jobs import JobQueue
from agent.platform.links import LinkError, LinkStore
from agent.platform.storage import Storage
from agent.config import Settings
from agent.ui.theme import Theme

ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


class FakeMessage:
    def __init__(self, text="", *, reply_to=None, uid=11):
        self.text = text
        self.reply_to_message = reply_to
        self.from_user = SimpleNamespace(id=uid)
        self.replies: list[str] = []
        #: (kind, path, caption) for every file this fake delivered.
        self.sent_files: list[tuple[str, str, str]] = []

    async def reply(self, text, **_kwargs):
        self.replies.append(text)

    async def reply_document(self, document=None, caption=None, **_kwargs):
        self.sent_files.append(("document", str(document), caption or ""))
        return SimpleNamespace(id=1)

    async def reply_video(self, video=None, caption=None, **_kwargs):
        self.sent_files.append(("video", str(video), caption or ""))
        return SimpleNamespace(id=1)


class FakeMedia:
    def __init__(self, path, name="clip.mp4"):
        self.file_name = name
        self._path = path


class FakeReply:
    """Stands in for the replied-to Message, which owns download()."""

    def __init__(self, media):
        self.document = media
        self.video = None

    async def download(self):
        return str(self.document._path)


@pytest.fixture()
def ctx(tmp_path):
    settings = Settings.from_env(ENV)
    return ModuleContext(
        settings=settings,
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "test-secret"),
    )


@pytest.fixture(scope="module")
def media_file(tmp_path_factory):
    target = tmp_path_factory.mktemp("m") / "clip.mp4"
    subprocess.run(
        [encoder.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=96x64:rate=8",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)],
        check=True, timeout=120,
    )
    return target


def run(handler, ctx, message):
    asyncio.run(handler(None, message))


def token_from(reply: str) -> str:
    """The token inside the share card's deep link (``?start=link_<token>``)."""
    match = re.search(r"(?:start=link_|link_)([^\s<&]+)", reply)
    return match.group(1) if match else ""


# --- encoder ---------------------------------------------------------------


def test_encoder_manifest_matches_its_handlers(ctx):
    manifest, handlers = encoder.build(ctx)

    assert set(manifest.commands) == set(handlers)
    assert manifest.slug == "encoder"


def test_encode_without_a_reply_explains_itself(ctx):
    _, handlers = encoder.build(ctx)
    message = FakeMessage("/encode")

    run(handlers["encode"], ctx, message)

    assert "Reply to a video" in message.replies[0]


def test_encode_rejects_unknown_preset(ctx, media_file):
    _, handlers = encoder.build(ctx)
    message = FakeMessage("/encode ultra", reply_to=FakeReply(FakeMedia(media_file)))

    run(handlers["encode"], ctx, message)

    assert "fast|balanced|quality" in message.replies[0]


def test_encinfo_reports_real_media(ctx, media_file):
    _, handlers = encoder.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    message = FakeMessage("/mediainfo", reply_to=reply)

    run(handlers["mediainfo"], ctx, message)

    assert "h264" in message.replies[0]
    assert "96x64" in message.replies[0]


def test_encode_runs_a_real_job(ctx, media_file):
    _, handlers = encoder.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    message = FakeMessage("/encode fast", reply_to=reply)

    run(handlers["encode"], ctx, message)

    assert any("Encoding job" in r for r in message.replies)
    assert any("finished" in r for r in message.replies)


# --- linkshare -------------------------------------------------------------


def test_linkshare_manifest_matches_its_handlers(ctx):
    manifest, handlers = linkshare.build(ctx)

    assert set(manifest.commands) == set(handlers)


def test_genlink_without_a_file_explains_itself(ctx):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage("/genlink")

    run(handlers["genlink"], ctx, message)

    assert "Reply to a file" in message.replies[0]


def test_genlink_creates_a_resolvable_link(ctx, media_file):
    _, handlers = linkshare.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    message = FakeMessage("/genlink 6", reply_to=reply)

    run(handlers["genlink"], ctx, message)

    assert "Share link" in message.replies[0]
    assert "t.me/" in message.replies[0] or "link_" in message.replies[0]
    token = token_from(message.replies[0])
    record = ctx.links.resolve(token)
    assert record.file_id
    assert record.max_uses == 0          # no cap unless one is asked for


def test_genlink_takes_a_use_cap_and_the_cap_is_real(ctx, media_file):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage("/genlink 6 2", reply_to=FakeReply(FakeMedia(media_file)))

    run(handlers["genlink"], ctx, message)

    token = token_from(message.replies[0])
    record = ctx.links.resolve(token)
    assert record.max_uses == 2
    assert record.remaining == 2
    assert "2 of 2 left" in message.replies[0]

    ctx.links.consume(token)
    ctx.links.consume(token)
    assert ctx.links.get(token).remaining == 0
    with pytest.raises(LinkError):
        ctx.links.resolve(token)


def test_genlink_rejects_a_bad_ttl(ctx, media_file):
    _, handlers = linkshare.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    message = FakeMessage("/genlink soon", reply_to=reply)

    run(handlers["genlink"], ctx, message)

    assert "whole number" in message.replies[0]


def test_links_is_empty_for_a_new_user(ctx):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage("/links")

    run(handlers["links"], ctx, message)

    assert "no links yet" in message.replies[0]


def test_links_lists_a_created_link(ctx, media_file):
    _, handlers = linkshare.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    run(handlers["genlink"], ctx, FakeMessage("/genlink", reply_to=reply))

    listing = FakeMessage("/links")
    run(handlers["links"], ctx, listing)

    assert "live" in listing.replies[0]
    assert "clip.mp4" in listing.replies[0]


def test_revoke_requires_a_token(ctx):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage("/revoke")

    run(handlers["revoke"], ctx, message)

    assert "Usage" in message.replies[0]


def test_revoke_rejects_an_unknown_token(ctx):
    _, handlers = linkshare.build(ctx)
    message = FakeMessage("/revoke totally-made-up")

    run(handlers["revoke"], ctx, message)

    assert "Invalid link" in message.replies[0]


def test_revoke_works_for_the_owner(ctx, media_file):
    _, handlers = linkshare.build(ctx)
    reply = FakeReply(FakeMedia(media_file))
    created = FakeMessage("/genlink", reply_to=reply)
    run(handlers["genlink"], ctx, created)
    token = token_from(created.replies[0])

    revoked = FakeMessage(f"/revoke {token}")
    run(handlers["revoke"], ctx, revoked)

    assert "Link revoked." in revoked.replies[0]
