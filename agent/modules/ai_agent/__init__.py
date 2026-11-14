"""AI Agent: explicit, stateless questions; no autonomous moderation or tools."""
from __future__ import annotations

import asyncio
import html
import json
import re
import time
from collections import OrderedDict
from dataclasses import replace

import aiohttp

from ...platform.manifest import PluginManifest
from ...utils.rich import reply

MANIFEST = PluginManifest(
    slug='ai_agent', name='AI Agent', version='1.0.0',
    description='Answer an explicit question through a configured AI provider; no chat-history collection or moderation powers.',
    commands=('ask',), permissions=('messages.read', 'messages.send', 'network'), scope='all',
    config_schema={'AI_API_KEY': 'secret; deployment environment only', 'AI_MODEL': 'required model id'},
)


class AIUnavailable(RuntimeError):
    pass


async def complete(key, model, question):
    """A fixed HTTPS endpoint; never accept a provider URL from a chat message."""
    try:
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + key}, allow_redirects=False,
                json={'model': model, 'messages': [
                    {'role': 'system', 'content': 'You are Agent, a helpful Telegram assistant. Answer concisely. You cannot perform Telegram actions or access group records. Do not claim to have done so.'},
                    {'role': 'user', 'content': question},
                ], 'max_completion_tokens': 700}) as response:
                if response.status == 429:
                    raise AIUnavailable('The AI provider is rate limited. Try again later.')
                if response.status != 200:
                    raise AIUnavailable('The AI provider refused this request. Ask the Owner to check provider configuration.')
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(8192):
                    size += len(chunk)
                    if size > 65536:
                        raise AIUnavailable('The AI response exceeded the safety limit.')
                    chunks.append(chunk)
                body = json.loads(b''.join(chunks))
                answer = body['choices'][0]['message']['content']
                if not isinstance(answer, str) or not answer.strip():
                    raise AIUnavailable('The AI provider returned no text answer.')
                return answer.strip()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, IndexError, TypeError):
        raise AIUnavailable('The AI request could not be completed. No group action was taken.') from None


def build(ctx):
    key = getattr(ctx.settings, 'ai_api_key', None)
    model = getattr(ctx.settings, 'ai_model', None)
    if not key or not model:
        return replace(MANIFEST, commands=(), description=MANIFEST.description + ' — unavailable in this deployment: configure AI_API_KEY and AI_MODEL'), {}
    requests = asyncio.Semaphore(2)
    recent = OrderedDict()

    async def ask(_client, message):
        user = getattr(message, 'from_user', None)
        if user is None:
            return
        parts = (getattr(message, 'text', '') or '').split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            await reply(message, 'Use <code>/ask your question</code>. Only your question is sent to the external AI provider; group history is not included. AI answers can be wrong.')
            return
        question = parts[1].strip()
        if len(question) > 2000:
            await reply(message, 'Keep your question within 2,000 characters. Do not include tokens or private credentials.')
            return
        if re.search(r"\b[0-9]{6,12}:[A-Za-z0-9_-]{25,}\b|\bsk-[A-Za-z0-9_-]{16,}\b", question):
            await reply(message, 'This looks like it contains credentials. Remove secrets before asking AI Agent; nothing was sent to the provider.')
            return
        now = time.monotonic()
        if now - recent.get(user.id, -1000) < 10:
            await reply(message, 'Please wait 10 seconds between AI requests.')
            return
        if requests.locked():
            await reply(message, 'AI Agent is busy. Please try again shortly.')
            return
        recent[user.id] = now
        recent.move_to_end(user.id)
        while len(recent) > 1000:
            recent.popitem(last=False)
        async with requests:
            try:
                answer = await complete(key, model, question)
                # Bound escaped length so HTML entities do not exceed message size.
                raw = answer
                answer = html.escape(raw[:3000])
                if len(answer) > 3500:
                    answer = html.escape(raw[:500])  # rare markup-heavy provider output
                await reply(message, f'<b>AI Agent</b>\n{answer}\n\n<i>AI-generated; verify important information. Your question was sent to an external AI provider.</i>')
            except AIUnavailable as exc:
                await reply(message, str(exc))

    return MANIFEST, {'ask': ask}
