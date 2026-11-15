"""AI Agent: explicit, stateless questions; no autonomous moderation or tools."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import replace

import aiohttp

from ...platform.manifest import PluginManifest
from ...utils.rich import reply
from ...ui.tables import panel

logger = logging.getLogger(__name__)


def card(title, text, *, note=None):
    return panel(
        title, lines=[text], note=note, footer="Meiko · /ask question · /help ask"
    )


def answer_preview(raw, budget=2600):
    """Bound escaped UTF-16 units without splitting entities or surrogate pairs."""
    pieces, size = [], 0
    for char in raw:
        escaped = html.escape(char)
        units = len(escaped.encode("utf-16-le")) // 2
        if size + units > budget:
            return "".join(pieces), True
        pieces.append(escaped)
        size += units
    return "".join(pieces), False


MANIFEST = PluginManifest(
    slug="ai_agent",
    name="AI Agent",
    version="1.0.0",
    description="Answer an explicit question through a configured AI provider; no chat-history collection or moderation powers.",
    commands=("ask",),
    permissions=("messages.read", "messages.send", "network"),
    scope="all",
    config_schema={
        "AI_API_KEY": "secret; deployment environment only",
        "AI_MODEL": "required model id",
    },
)


class AIUnavailable(RuntimeError):
    pass


async def complete(key, model, question):
    """A fixed HTTPS endpoint; never accept a provider URL from a chat message."""
    try:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                allow_redirects=False,
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are Meiko, a helpful Telegram assistant. Answer concisely. You cannot perform Telegram actions or access group records. Do not claim to have done so.",
                        },
                        {"role": "user", "content": question},
                    ],
                    "max_completion_tokens": 700,
                },
            ) as response:
                if response.status == 429:
                    raise AIUnavailable(
                        "The AI provider is rate limited. Try again later."
                    )
                if response.status != 200:
                    raise AIUnavailable(
                        "The AI provider refused this request. Ask the Owner to check provider configuration."
                    )
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(8192):
                    size += len(chunk)
                    if size > 65536:
                        raise AIUnavailable(
                            "The AI response exceeded the safety limit."
                        )
                    chunks.append(chunk)
                body = json.loads(b"".join(chunks))
                answer = body["choices"][0]["message"]["content"]
                if not isinstance(answer, str) or not answer.strip():
                    raise AIUnavailable("The AI provider returned no text answer.")
                return answer.strip()
    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ):
        raise AIUnavailable(
            "The AI request could not be completed. No group action was taken."
        ) from None


def build(ctx):
    key = getattr(ctx.settings, "ai_api_key", None)
    model = getattr(ctx.settings, "ai_model", None)
    if not key or not model:
        return replace(
            MANIFEST,
            commands=(),
            description=MANIFEST.description
            + " — unavailable in this deployment: configure AI_API_KEY and AI_MODEL",
        ), {}
    requests = asyncio.Semaphore(2)
    recent = OrderedDict()

    async def ask(_client, message):
        user = getattr(message, "from_user", None)
        if (
            type(getattr(user, "id", None)) is not int
            or user.id <= 0
            or getattr(message, "sender_chat", None) is not None
        ):
            await reply(
                message,
                card(
                    "AI Agent identity required",
                    "Ask as yourself using your personal Telegram identity. No question was sent.",
                ),
            )
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            await reply(
                message,
                card(
                    "AI Agent · Ask Meiko",
                    "Use <code>/ask your question</code> with any supported prefix: / ! . ?",
                    note="Only your question is sent to the external AI provider; group history is not included. AI answers can be wrong. Do not send secrets.",
                ),
            )
            return
        question = parts[1].strip()
        if len(question) > 2000:
            await reply(
                message,
                card(
                    "AI Agent · Question too long",
                    "Keep your question within 2,000 characters. Do not include tokens or private credentials. Nothing was sent.",
                ),
            )
            return
        if re.search(
            r"\b[0-9]{6,12}:[A-Za-z0-9_-]{25,}\b|\bsk-[A-Za-z0-9_-]{16,}\b", question
        ):
            await reply(
                message,
                card(
                    "AI Agent · Credentials blocked",
                    "This looks like it contains credentials. Remove secrets before asking AI Agent; nothing was sent to the provider.",
                ),
            )
            return
        now = time.monotonic()
        if now - recent.get(user.id, -1000) < 10:
            await reply(
                message,
                card(
                    "AI Agent · Cooldown",
                    "Please wait 10 seconds between AI requests. Nothing was sent for this request.",
                ),
            )
            return
        if requests.locked():
            await reply(
                message,
                card(
                    "AI Agent · Busy",
                    "AI Agent is busy. Please try again shortly. Nothing was sent for this request.",
                ),
            )
            return
        recent[user.id] = now
        recent.move_to_end(user.id)
        while len(recent) > 1000:
            recent.popitem(last=False)
        async with requests:
            try:
                answer = await complete(key, model, question)
            except AIUnavailable as exc:
                await reply(
                    message,
                    card("AI Agent · Provider unavailable", html.escape(str(exc))),
                )
                return
            except Exception:
                logger.warning(
                    "AI provider outcome unconfirmed; no automatic retry attempted."
                )
                await reply(
                    message,
                    card(
                        "AI Agent · Request unconfirmed",
                        "The provider request could not be confirmed. No Telegram action was taken. No automatic retry was attempted.",
                    ),
                )
                return
            preview, shortened = answer_preview(answer)
            await reply(
                message,
                card(
                    "AI Agent · Meiko",
                    preview,
                    note=(
                        "Answer shortened to fit Telegram. Ask a narrower follow-up if needed. "
                        if shortened
                        else ""
                    )
                    + "AI-generated; verify important information. Your question was sent to an external AI provider. No group records or Telegram actions are available to this assistant.",
                ),
            )

    return MANIFEST, {"ask": ask}
