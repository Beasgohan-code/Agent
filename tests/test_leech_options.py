"""Output naming reaches real transfer/delivery and survives cleanup boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import leech
from agent.modules.leech.options import parse_request
from agent.platform.media_rules import REPLACE_KEY
from test_plugins import make_ctx, FakeMessage, OWNER, CHAT


@pytest.mark.parametrize(
    "text",
    [
        "/leech url -n ../file",
        '/leech url -n "a/b"',
        '/leech url -n "a\\\\b"',
        "/leech url -n ..",
        '/leech url -n ""',
        '/leech url -n "unterminated',
        "/leech url -x output",
        "/leech url -n " + "a" * 121,
    ],
)
def test_invalid_names_refused_before_network(tmp_path, monkeypatch, text):
    async def scenario():
        ctx = make_ctx(tmp_path)
        check = AsyncMock()
        monkeypatch.setattr(leech, "check_target", check)
        request = FakeMessage(text)
        await leech.build(ctx)[1]["leech"](None, request)
        check.assert_not_awaited()
        assert not ctx.jobs.active()
        assert "Usage" in request.replies[-1]

    asyncio.run(scenario())


def test_legacy_and_quoted_name_syntax():
    assert parse_request("/leech https://example.com/a?x=1&y=2") == (
        "https://example.com/a?x=1&y=2",
        None,
    )
    assert parse_request('/mirror https://example.com/a -n "Movie Name.mkv"') == (
        "https://example.com/a",
        "Movie Name.mkv",
    )


@pytest.mark.parametrize("kind", ["leech", "mirror"])
def test_named_transfer_and_media_rules_keep_final_copy_only(
    tmp_path, monkeypatch, kind
):
    async def scenario():
        ctx = make_ctx(tmp_path)
        ctx.chats.put(CHAT, REPLACE_KEY, {"Old": "New", "New": "Other"})
        created = []

        def destination(url, name=None):
            folder = tmp_path / "transfer"
            folder.mkdir()
            target = folder / name
            created.append(target)
            return target

        async def download(url, target, **kwargs):
            target.write_bytes(b"payload")
            return 7

        monkeypatch.setattr(leech, "_destination", destination)
        monkeypatch.setattr(leech, "check_target", AsyncMock())
        monkeypatch.setattr(leech, "download", download)
        client = SimpleNamespace(
            send_document=AsyncMock(), edit_message_text=AsyncMock()
        )
        await leech.build(ctx)[1][kind](
            client, FakeMessage(f"/{kind} https://example.com/a -n Old.mkv")
        )
        job = ctx.jobs.for_owner(OWNER)[0]
        await job.task
        assert job.state.value == "done"
        assert not created[0].exists() and not created[0].parent.exists()
        if kind == "leech":
            assert client.send_document.await_args.kwargs["file_name"] == "New.mkv"
        else:
            saved = ctx.storage.list_owned(OWNER)[0]
            assert saved.name == "New.mkv"
            assert ctx.storage.path_for(saved).read_bytes() == b"payload"

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_failed_or_cancelled_transfer_cleans_partial(tmp_path, monkeypatch, failure):
    async def scenario():
        ctx = make_ctx(tmp_path)
        folder = tmp_path / "transfer"
        folder.mkdir()
        target = folder / "partial"
        monkeypatch.setattr(leech, "_destination", lambda *args: target)
        monkeypatch.setattr(leech, "check_target", AsyncMock())

        async def download(*args, **kwargs):
            target.write_bytes(b"partial")
            raise failure()

        monkeypatch.setattr(leech, "download", download)
        await leech.build(ctx)[1]["leech"](
            None, FakeMessage("/leech https://example.com/a")
        )
        await asyncio.gather(ctx.jobs.for_owner(OWNER)[0].task, return_exceptions=True)
        assert not target.exists() and not folder.exists()

    asyncio.run(scenario())


def test_replied_url_options_are_unambiguous_and_preserve_query():
    from agent.modules.leech.options import parse_message

    request = SimpleNamespace(
        text='/leech -n "Movie Name.mkv"',
        reply_to_message=SimpleNamespace(text="https://example.com/a?x=1&y=2"),
    )
    assert parse_message(request) == ("https://example.com/a?x=1&y=2", "Movie Name.mkv")
    request.text = "/mirror"
    assert parse_message(request) == ("https://example.com/a?x=1&y=2", None)
    request.reply_to_message.text = "https://example.com/a\nhttps://example.com/b"
    with pytest.raises(ValueError):
        parse_message(request)


def test_replied_url_reaches_real_transfer_submission(tmp_path, monkeypatch):
    async def scenario():
        ctx = make_ctx(tmp_path)
        source = "https://example.com/a?x=1&y=2"
        check = AsyncMock()
        monkeypatch.setattr(leech, "check_target", check)

        async def download(url, target, **kwargs):
            assert url == source
            target.write_bytes(b"payload")
            return 7

        monkeypatch.setattr(leech, "download", download)
        client = SimpleNamespace(
            send_document=AsyncMock(), edit_message_text=AsyncMock()
        )
        request = FakeMessage('/leech -n "Movie.mkv"')
        request.reply_to_message = SimpleNamespace(text=source)
        await leech.build(ctx)[1]["leech"](client, request)
        job = ctx.jobs.for_owner(OWNER)[0]
        await job.task
        assert job.state.value == "done"
        check.assert_awaited_once_with(source)
        assert client.send_document.await_args.kwargs["file_name"] == "Movie.mkv"

    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [RuntimeError, asyncio.CancelledError])
def test_transfer_failure_and_cancel_notify_without_exposing_secrets(tmp_path, monkeypatch, failure):
    async def scenario():
        ctx = make_ctx(tmp_path)
        monkeypatch.setattr(leech, 'check_target', AsyncMock())
        async def download(url, target, **kwargs):
            target.write_bytes(b'partial')
            raise failure('secret-source-value')
        monkeypatch.setattr(leech, 'download', download)
        message = FakeMessage('/leech https://example.com/file')
        await leech.build(ctx)[1]['leech'](None, message)
        job = ctx.jobs.for_owner(OWNER)[0]
        await asyncio.gather(job.task, return_exceptions=True)
        text = '\n'.join(message.replies)
        assert ('Transfer cancelled' if failure is asyncio.CancelledError else 'Transfer failed') in text
        assert 'secret-source-value' not in text
        assert job.state.value == ('cancelled' if failure is asyncio.CancelledError else 'failed')
    asyncio.run(scenario())
