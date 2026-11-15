"""Provider-backed AI behavior; no live paid API requests in the test suite."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.modules import ai_agent
from agent.config import Settings
from test_config import VALID_ENV


def context(key="test-provider-secret", model="configured-model"):
    return SimpleNamespace(settings=SimpleNamespace(ai_api_key=key, ai_model=model))


def message(text="/ask hello"):
    return SimpleNamespace(
        text=text, from_user=SimpleNamespace(id=22), reply=AsyncMock()
    )


@pytest.mark.parametrize("key,model", [(None, None), ("key", None), (None, "model")])
def test_unconfigured_provider_registers_no_command(key, model):
    manifest, handlers = ai_agent.build(context(key, model))
    assert not manifest.commands and not handlers
    assert "unavailable" in manifest.description


def test_ask_uses_only_explicit_question_and_escapes_output(monkeypatch):
    async def scenario():
        provider = AsyncMock(return_value="<b>not trusted HTML</b>")
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        request = message("/ask one explicit question")
        await commands["ask"](None, request)
        provider.assert_awaited_once_with(
            "test-provider-secret", "configured-model", "one explicit question"
        )
        body = request.reply.await_args.args[0]
        assert "&lt;b&gt;not trusted HTML&lt;/b&gt;" in body
        assert "external AI provider" in body

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text",
    [
        "/ask",
        "/ask " + "x" * 2001,
        "/ask 111111111:AAHfakeTokenValueForTests_aaaaaaaa",
        "/ask sk-abcdefghijklmnopabcdefghijklmnop",
    ],
)
def test_invalid_or_sensitive_question_never_reaches_provider(monkeypatch, text):
    async def scenario():
        provider = AsyncMock()
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        await commands["ask"](None, message(text))
        provider.assert_not_awaited()

    asyncio.run(scenario())


def test_per_user_cooldown_bounds_provider_requests(monkeypatch):
    async def scenario():
        provider = AsyncMock(return_value="answer")
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        await commands["ask"](None, message())
        second = message()
        await commands["ask"](None, second)
        provider.assert_awaited_once()
        assert "wait 10 seconds" in second.reply.await_args.args[0]

    asyncio.run(scenario())


def test_provider_failure_is_reported_without_canned_success(monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            ai_agent,
            "complete",
            AsyncMock(side_effect=ai_agent.AIUnavailable("Provider unavailable.")),
        )
        _, commands = ai_agent.build(context())
        request = message()
        await commands["ask"](None, request)
        assert "Provider unavailable." in request.reply.await_args.args[0]

    asyncio.run(scenario())


class Response:
    def __init__(self, status=200, raw=None):
        self.status = status
        self.raw = (
            raw
            if raw is not None
            else json.dumps(
                {"choices": [{"message": {"content": "real provider output"}}]}
            ).encode()
        )
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for i in range(0, len(self.raw), size):
            yield self.raw[i : i + size]


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_provider_transport_is_fixed_https_and_does_not_follow_redirects(monkeypatch):
    session = Session(Response())
    monkeypatch.setattr(ai_agent.aiohttp, "ClientSession", lambda **kwargs: session)
    assert (
        asyncio.run(ai_agent.complete("secret", "model", "question"))
        == "real provider output"
    )
    url, kwargs = session.calls[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"]["messages"][-1] == {"role": "user", "content": "question"}
    assert len(kwargs["json"]["messages"]) == 2
    assert "You are Meiko" in kwargs["json"]["messages"][0]["content"]


@pytest.mark.parametrize(
    "response",
    [
        Response(401),
        Response(429),
        Response(302),
        Response(raw=b"not json"),
        Response(raw=b"x" * 65537),
    ],
)
def test_provider_errors_and_oversize_responses_are_sanitized(monkeypatch, response):
    monkeypatch.setattr(
        ai_agent.aiohttp, "ClientSession", lambda **kwargs: Session(response)
    )
    with pytest.raises(ai_agent.AIUnavailable) as error:
        asyncio.run(ai_agent.complete("secret-key-never-print", "model", "question"))
    assert "secret-key-never-print" not in str(error.value)


def test_ai_key_is_loaded_without_exposure_in_settings_repr():
    settings = Settings.from_env(
        {**VALID_ENV, "AI_API_KEY": "private-ai-key", "AI_MODEL": "chosen-model"}
    )
    assert settings.ai_api_key == "private-ai-key"
    assert settings.ai_model == "chosen-model"
    assert "private-ai-key" not in repr(settings)


def test_ai_studio_uses_meiko_panels_and_marks_shortened_output(monkeypatch):
    from agent.ui import tables

    async def scenario():
        tables.set_rich(True)
        provider = AsyncMock(return_value="😀<&" * 3000)
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        request = message("!ask explain")
        await commands["ask"](None, request)
        body = request.reply.await_args.args[0]
        assert "Meiko" in body and "AI Agent" in body
        assert "shortened" in body.lower()
        assert len(str(body).encode("utf-16-le")) // 2 < 4096
        assert "AI-generated" in body and "external AI provider" in body

    asyncio.run(scenario())


def test_anonymous_ai_requests_never_reach_provider(monkeypatch):
    async def scenario():
        provider = AsyncMock()
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        request = message(".ask hello")
        request.sender_chat = SimpleNamespace(id=-100)
        await commands["ask"](None, request)
        provider.assert_not_awaited()

    asyncio.run(scenario())


def test_unexpected_provider_failure_is_sanitized_and_delivery_not_retried(monkeypatch):
    async def scenario():
        provider = AsyncMock(side_effect=RuntimeError("secret-provider-key"))
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        request = message("?ask hello")
        await commands["ask"](None, request)
        body = request.reply.await_args.args[0]
        assert "secret-provider-key" not in body
        assert "unconfirmed" in body.lower()
        provider.assert_awaited_once()

    asyncio.run(scenario())


def test_ai_concurrency_limit_does_not_queue_extra_provider_requests(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()
        count = 0

        async def provider(*args):
            nonlocal count
            count += 1
            if count == 2:
                started.set()
            await release.wait()
            return "answer"

        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        requests = [message("!ask hello") for _ in range(3)]
        for i, request in enumerate(requests):
            request.from_user.id = 22 + i
        tasks = [asyncio.create_task(commands["ask"](None, r)) for r in requests[:2]]
        try:
            await asyncio.wait_for(started.wait(), 1)
            await commands["ask"](None, requests[2])
            assert count == 2
            assert "busy" in requests[2].reply.await_args.args[0].lower()
            release.set()
            await asyncio.gather(*tasks)
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_answer_delivery_error_is_not_reported_as_provider_error_or_retried(
    monkeypatch,
):
    async def scenario():
        provider = AsyncMock(return_value="answer")
        monkeypatch.setattr(ai_agent, "complete", provider)
        _, commands = ai_agent.build(context())
        request = message(".ask hello")
        request.reply.side_effect = TimeoutError("delivery ambiguous")
        with pytest.raises(TimeoutError):
            await commands["ask"](None, request)
        request.reply.assert_awaited_once()
        provider.assert_awaited_once()

    asyncio.run(scenario())
