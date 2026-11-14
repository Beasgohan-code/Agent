"""The renamer engine and its commands."""

import asyncio
from types import SimpleNamespace

import pytest

from agent.config import Settings
from agent.modules import renamer
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


class FakeClient:
    def __init__(self):
        self.documents = []

    async def send_document(self, chat_id, document, file_name=None, caption=None, **kwargs):
        self.documents.append((chat_id, document, file_name, caption))
        return SimpleNamespace(id=1)


class FakeMessage:
    def __init__(self, text="", *, file_name=None, file_id="BAADBAAD"):
        self.text = text
        self.chat = SimpleNamespace(id=7)
        self.from_user = SimpleNamespace(id=11, first_name="Ada")
        self.id = 100
        media = (
            SimpleNamespace(file_name=file_name, file_id=file_id, caption="original caption")
            if file_name
            else None
        )
        self.reply_to_message = SimpleNamespace(document=media) if media else None
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(delete=lambda: None)


@pytest.fixture()
def ctx(tmp_path):
    return ModuleContext(
        settings=Settings.from_env(ENV),
        theme=Theme(),
        sender=None,
        jobs=JobQueue(),
        storage=Storage(tmp_path / "storage"),
        links=LinkStore(tmp_path / "links", "secret"),
        chats=ChatStore(tmp_path),
    )


def run(handler, ctx, message, client=None):
    return asyncio.run(handler(client, message))


def handlers(ctx):
    return renamer.build(ctx)[1]


# --- engine ----------------------------------------------------------------


def test_a_typical_episode_becomes_a_clean_name():
    planned, warnings = renamer.plan_name("Show.Name.S02E05.1080p.WEB-DL.x264-GROUP.mkv")

    assert planned == "Show Name S02E05 [1080p].mkv"
    assert warnings == []


def test_the_movie_template_keeps_the_year():
    planned, _ = renamer.plan_name(
        "Some.Movie.2023.2160p.NF.mkv", "{title} ({year}) [{quality}]"
    )

    assert planned == "Some Movie 2023 (2023) [2160p].mkv"


def test_a_missing_quality_says_unknown_rather_than_guessing():
    planned, _ = renamer.plan_name("Clip.mkv")

    assert "Unknown" in planned


def test_unknown_template_fields_are_left_visible():
    planned, _ = renamer.plan_name("Movie.2023.mkv", "{title} {bogus}")

    assert "{bogus}" in planned


def test_an_invalid_template_falls_back_with_a_warning():
    planned, warnings = renamer.plan_name("Movie.2023.1080p.mkv", "{title:bad}")

    assert planned.endswith(".mkv")
    assert warnings


def test_unsafe_characters_are_replaced():
    planned, _ = renamer.plan_name('A/B:C*D.mkv', "{title}")

    assert "/" not in planned
    assert ":" not in planned


def test_clean_strips_release_noise_but_keeps_the_year_and_extension():
    assert renamer.clean_filename("Some.Movie.2023.1080p.BluRay.x265-YIFY.mkv") == (
        "Some Movie 2023.mkv"
    )


def test_extension_survives_a_long_name():
    long_name = f"{'word.' * 40}1080p.mkv"

    planned, warnings = renamer.plan_name(long_name)

    assert planned.endswith(".mkv")
    assert len(planned) <= renamer.MAX_NAME
    assert warnings


# --- commands --------------------------------------------------------------


def test_autorename_without_arguments_shows_the_current_template(ctx):
    message = FakeMessage("/autorename")

    run(handlers(ctx)["autorename"], ctx, message)

    assert renamer.DEFAULT_TEMPLATE in message.replies[0]


def test_autorename_saves_and_previews(ctx):
    message = FakeMessage("/autorename {title} [{quality}]")

    run(handlers(ctx)["autorename"], ctx, message)

    assert ctx.chats.get(7, renamer.TEMPLATE_KEY) == "{title} [{quality}]"
    assert "Preview:" in message.replies[0]


def test_autorename_rejects_a_template_with_no_fields(ctx):
    message = FakeMessage("/autorename plain text")

    run(handlers(ctx)["autorename"], ctx, message)

    assert "needs at least one field" in message.replies[0]
    assert ctx.chats.get(7, renamer.TEMPLATE_KEY) is None


def test_testrename_previews_a_filename(ctx):
    message = FakeMessage("/testrename Show.S01E02.720p.mkv")

    run(handlers(ctx)["testrename"], ctx, message)

    assert "Show S01E02 [720p].mkv" in message.replies[0]


def test_testrename_uses_the_chat_template(ctx):
    ctx.chats.put(7, renamer.TEMPLATE_KEY, "{title}")

    message = FakeMessage("/testrename Show.S01E02.720p.mkv")
    run(handlers(ctx)["testrename"], ctx, message)

    assert "To: <code>Show.mkv</code>" in message.replies[0]


def test_rename_reuploads_with_the_new_name(ctx):
    client = FakeClient()
    message = FakeMessage("/rename", file_name="Show.S01E02.720p.mkv")

    run(handlers(ctx)["rename"], ctx, message, client)

    chat_id, document, file_name, caption = client.documents[0]
    assert chat_id == 7
    assert document == "BAADBAAD"
    assert file_name == "Show S01E02 [720p].mkv"
    assert caption == "original caption"
    assert "Renamed" in message.replies[0]


def test_rename_without_a_file_explains_itself(ctx):
    message = FakeMessage("/rename")

    run(handlers(ctx)["rename"], ctx, message, FakeClient())

    assert "Reply to a file" in message.replies[0]


def test_rename_reports_a_telegram_failure(ctx):
    class Broken(FakeClient):
        async def send_document(self, *args, **kwargs):
            raise RuntimeError("file reference expired")

    message = FakeMessage("/rename", file_name="Show.S01E02.mkv")

    run(handlers(ctx)["rename"], ctx, message, Broken())

    assert "Rename failed" in message.replies[0]


def test_clean_shows_a_tidier_name(ctx):
    message = FakeMessage("/clean Some.Release.1080p.x264.mkv")

    run(handlers(ctx)["clean"], ctx, message)

    assert "Some Release.mkv" in message.replies[0]


def test_the_manifest_matches_the_handlers(ctx):
    manifest, built = renamer.build(ctx)

    assert set(manifest.commands) == set(built)


def test_renamemode_is_not_registered_on_purpose(ctx):
    # It switches automatic renaming inside an upload pipeline this bot does
    # not have, so registering it would be a control with nothing behind it.
    manifest, _ = renamer.build(ctx)

    assert "renamemode" not in manifest.commands
