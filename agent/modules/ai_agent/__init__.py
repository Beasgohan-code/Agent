"""AI Agent: explicit questions and opt-in stateless chat; no moderation tools."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
import secrets
from collections import OrderedDict
from dataclasses import replace
from types import SimpleNamespace

from pyrogram import filters
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.handlers import MessageHandler
from pyrogram.types import InputRichMessage
from richgram import rich_thinking

import aiohttp

from ...platform.manifest import PluginManifest
from ...utils.rich import reply
from ...ui.tables import panel
from ...ui.identity import controller_label

logger = logging.getLogger(__name__)


def card(title, text, *, note=None):
    return panel(
        title, lines=[text], note=note, footer=controller_label("Meiko · /ask question · /help ask", "/ask question · /help ask")
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
    group_compatible=True,
    clone_compatible=True,
    required_credentials=("ai_api_key", "ai_model"),
    slug="ai_agent",
    name="AI Agent",
    version="1.0.0",
    description="Explicit questions and opt-in private/group-directed chat through a configured AI provider; no chat-history collection or moderation powers.",
    commands=("ask", "autochat"),
    permissions=("messages.read", "messages.send", "network"),
    scope="all",
    config_schema={
        "AI_API_KEY": "secret; deployment environment only",
        "AI_MODEL": "required model id",
    },
)


class AIUnavailable(RuntimeError):
    pass


async def complete(key, model, question, on_delta=None):
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
                            "content": controller_label("You are Meiko, a helpful Telegram assistant.", "You are a helpful Telegram assistant.") + " Answer concisely. You cannot perform Telegram actions or access group records. Do not claim to have done so.",
                        },
                        {"role": "user", "content": question},
                    ],
                    "max_completion_tokens": 700,
                    **({"stream": True} if on_delta else {}),
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
                if on_delta:
                    return await read_stream(response.content, on_delta)
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


async def read_stream(content, on_delta):
    """Bounded SSE parser: only answer deltas, never reasoning/tool events."""
    buffer, answer, size = b'', '', 0
    async for chunk in content.iter_chunked(8192):
        size += len(chunk)
        if size > 65536:
            raise AIUnavailable('The AI response exceeded the safety limit.')
        buffer += chunk
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if not line.startswith(b'data:'):
                continue
            data = line[5:].strip()
            if data == b'[DONE]':
                if not answer.strip():
                    raise AIUnavailable('The AI provider returned no text answer.')
                return answer.strip()
            event = json.loads(data)
            if 'error' in event:
                raise AIUnavailable('The AI provider interrupted this response.')
            choices = event.get('choices', [])
            if not choices:
                continue
            text = choices[0].get('delta', {}).get('content')
            if text is not None:
                if not isinstance(text, str):
                    raise AIUnavailable('The AI provider returned invalid text.')
                answer += text
                if text:
                    await on_delta(answer)
    # Never present a truncated transport as a successfully finished answer.
    raise AIUnavailable('The AI response was interrupted. No automatic retry was attempted.')


class AnswerDraft:
    """Best-effort ephemeral progress; failures never retry a provider request."""
    def __init__(self, client, message):
        self.client = client
        self.chat_id = getattr(getattr(message, 'chat', None), 'id', None)
        self.thread_id = getattr(message, 'message_thread_id', None)
        self.draft_id = secrets.randbits(63) or 1
        self.last = -100.0
        self.rich = callable(getattr(client, 'send_rich_message_draft', None))
        self.enabled = type(self.chat_id) is int and (self.rich or callable(getattr(client, 'send_message_draft', None)))

    async def update(self, text=''):
        now = time.monotonic()
        if not self.enabled or now - self.last < 1.5:
            return
        self.last = now
        escaped, _ = answer_preview(text)
        try:
            kwargs = dict(chat_id=self.chat_id, draft_id=self.draft_id,
                          message_thread_id=self.thread_id)
            if self.rich:
                await self.client.send_rich_message_draft(
                    **kwargs, rich_text=InputRichMessage(html=str(card(
                        controller_label('AI Agent · Meiko', 'AI Assistant'), escaped + rich_thinking(),
                        note='Generating an AI answer · external provider · no Telegram actions.'))))
            else:
                await self.client.send_message_draft(
                    **kwargs, text=(controller_label('Meiko · Generating…\n', 'Generating…\n') + text)[:3000], parse_mode=None)
        except Exception:
            # Drafts are cosmetic. Do not retry ambiguous/flood/permission errors.
            self.enabled = False


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
                    controller_label("AI Agent · Ask Meiko", "Ask a question"),
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
            draft = AnswerDraft(_client, message)
            await draft.update()
            try:
                if draft.enabled:
                    answer = await complete(key, model, question, on_delta=draft.update)
                else:
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
                    controller_label("AI Agent · Meiko", "AI Assistant"),
                    preview,
                    note=(
                        "Answer shortened to fit Telegram. Ask a narrower follow-up if needed. "
                        if shortened
                        else ""
                    )
                    + "AI-generated; verify important information. Your question was sent to an external AI provider. No group records or Telegram actions are available to this assistant.",
                ),
            )

    async def autochat(client, message):
        chat, user = getattr(message, 'chat', None), getattr(message, 'from_user', None)
        chat_id, uid = getattr(chat, 'id', None), getattr(user, 'id', None)
        if type(uid) is not int or uid <= 0 or getattr(message, 'sender_chat', None) is not None:
            await reply(message, 'Use your personal Telegram identity to configure auto-chat.')
            return
        private = getattr(chat, 'type', None) == ChatType.PRIVATE and chat_id == uid
        group = getattr(chat, 'type', None) in (ChatType.GROUP, ChatType.SUPERGROUP)
        if not private and not group:
            return
        if group:
            member = await client.get_chat_member(chat_id, uid)
            if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                await reply(message, 'Only group administrators can configure AI auto-chat.')
                return
        parts = (getattr(message, 'text', '') or '').split()
        action = parts[1].lower() if len(parts) == 2 else 'status' if len(parts) == 1 else ''
        if action not in ('on', 'off', 'status'):
            await reply(message, 'Use /autochat on|off|status.')
            return
        db, chats = getattr(ctx, 'db', None), getattr(ctx, 'chats', None)
        if chats is None or (db is not None and not db.connected):
            await reply(message, 'Auto-chat settings unavailable. No change confirmed.')
            return
        previous = chats.get(chat_id, 'ai_autochat', False)
        if action != 'status':
            enabled = action == 'on'
            try:
                chats.put(chat_id, 'ai_autochat', enabled)
                if db is not None and await db.flush() <= 0:
                    raise RuntimeError('unconfirmed write')
            except Exception:
                chats.put(chat_id, 'ai_autochat', previous)
                await reply(message, 'Auto-chat change unconfirmed; previous cached setting retained.')
                return
        enabled = chats.get(chat_id, 'ai_autochat', False) is True
        await reply(message, card('AI Agent · Auto-chat',
            f'State: <b>{"on" if enabled else "off"}</b>. ' +
            ('Ordinary private text can receive AI replies.' if private else controller_label('Only mentions of Meiko or replies to this bot can receive AI replies.', 'Only mentions of this bot or replies to it can receive AI replies.')),
            note='Only the triggering message goes to the external AI provider, without conversation history. Do not send secrets. Use /autochat off to stop; /ask remains available. Group Owner approval and plugin activation are still required.'))

    async def automatic(client, message):
        chat, user = getattr(message, 'chat', None), getattr(message, 'from_user', None)
        text = getattr(message, 'text', None)
        uid, chat_id = getattr(user, 'id', None), getattr(chat, 'id', None)
        if (type(uid) is not int or uid <= 0 or getattr(user, 'is_bot', False)
                or getattr(message, 'sender_chat', None) is not None
                or getattr(message, 'service', None) or getattr(message, 'via_bot', None)
                or any(getattr(message, field, None) for field in ('forward_origin', 'forward_date', 'forward_from', 'forward_from_chat', 'forward_sender_name'))
                or not isinstance(text, str) or not text.strip() or text.lstrip().startswith(('/', '!', '.', '#', '$', '%', '&', '?'))):
            return
        db, chats = getattr(ctx, 'db', None), getattr(ctx, 'chats', None)
        if chats is None or (db is not None and not db.connected) or chats.get(chat_id, 'ai_autochat', False) is not True:
            return
        if getattr(chat, 'type', None) == ChatType.PRIVATE:
            if chat_id != uid:
                return
        elif getattr(chat, 'type', None) in (ChatType.GROUP, ChatType.SUPERGROUP):
            me = getattr(client, 'me', None)
            if me is None:
                return
            replied_user = getattr(getattr(message, 'reply_to_message', None), 'from_user', None)
            is_reply = getattr(replied_user, 'id', None) == me.id
            username = getattr(me, 'username', None)
            mention = re.compile(r'(?<![\w@])@' + re.escape(username) + r'\b', re.I) if username else None
            if not is_reply and not (mention and mention.search(text)):
                return
            if mention:
                text = mention.sub('', text).strip()
            if not text:
                return
        else:
            return
        # Reuse the exact question validation/rate limits/provider boundary.
        request = SimpleNamespace(text='/ask ' + text, from_user=user, chat=chat,
                                  reply=message.reply, sender_chat=None,
                                  _client=getattr(message, '_client', None),
                                  id=getattr(message, 'id', None),
                                  message_thread_id=getattr(message, 'message_thread_id', None))
        await ask(client, request)

    ctx.ai_autochat_handler = automatic
    return MANIFEST, {"ask": ask, "autochat": autochat}


def extra_handlers(ctx):
    handler = getattr(ctx, 'ai_autochat_handler', None)
    return [MessageHandler(handler, filters.text)] if handler is not None else []
