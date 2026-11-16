"""Bounded private archive conversations matching the reviewed prompt sequence."""

import asyncio
import logging
import time
from types import SimpleNamespace

from ...utils.rich import reply
from .channel_links import archive_reference, private


logger = logging.getLogger(__name__)


class ArchiveConversation:
    def __init__(self, ctx, generate, *, clock=time.monotonic):
        self.ctx, self.generate, self.clock = ctx, generate, clock
        self.state = None
        self.lock = asyncio.Lock()

    async def start(self, client, message, mode):
        if not private(message) or message.from_user.id != self.ctx.settings.owner_id:
            await reply(
                message,
                "Only this bot’s Owner can build archive links in private chat.",
            )
            return
        async with self.lock:
            self.state = dict(
                mode=mode,
                owner=self.ctx.settings.owner_id,
                ids=[],
                seen=set(),
                expires=self.clock() + 300,
                channel=self.ctx.settings.storage_channel,
            )
        text = (
            "Send or forward ONE message to generate its delivery link. Existing configured-archive forwards or private archive links are also accepted."
            if mode == "genlink" else
            "Send or forward the FIRST archive message, or its private Telegram link."
            if mode == "batch"
            else "Send or forward each message you want to include, one by one. Send /done to link exactly the selected messages (up to 50)."
            if mode == 'custom_selection'
            else "Send or forward archive messages one by one. Send /done to create the first-to-last range link. All intervening messages are included."
        )
        await reply(
            message, text + "\nSend /cancel to cancel. Session expires in 5 minutes."
        )

    async def receive(self, client, message):
        if not private(message) or message.from_user.id != self.ctx.settings.owner_id:
            return
        async with self.lock:
            state = self.state
            if state is None:
                return
            text = (getattr(message, "text", None) or "").strip()
            command = text.split("@")[0].lower()
            if command == "/cancel":
                self.state = None
                await reply(
                    message, "Archive link creation cancelled. No link created. Existing archive copies are retained."
                )
                return
            if text.startswith("/") and command != "/done":
                return
            if (
                self.clock() >= state["expires"]
                or self.ctx.settings.storage_channel != state["channel"]
                or self.ctx.settings.owner_id != state['owner']
            ):
                self.state = None
                await reply(
                    message,
                    "Archive session expired or configuration changed. Start again; no link created.",
                )
                return
            if command == "/done":
                if state["mode"] not in ("custom_batch", "custom_selection") or not state["ids"]:
                    await reply(
                        message,
                        "No custom batch ready. Send an archive message first, or /cancel.",
                    )
                    return
                await self.finish(client, message, state)
                return
            if state['mode'] == 'custom_selection':
                input_id = getattr(message, 'id', None)
                if type(input_id) is not int or input_id <= 0:
                    await reply(message, 'Message identity unavailable. Resend it or /cancel.')
                    return
                if input_id in state['seen']:
                    await reply(message, 'This message was already collected. Send another, /done or /cancel.')
                    return
                if len(state['ids']) >= 50:
                    await reply(message, 'Batch limit reached (50). Send /done or /cancel; nothing else copied.')
                    return
            forwarded = getattr(message, "forward_from_chat", None)
            mid = getattr(message, "forward_from_message_id", None)
            origin = getattr(message, 'forward_origin', None)
            if getattr(origin, 'chat', None) is not None:
                forwarded, mid = origin.chat, getattr(origin, 'message_id', None)
            if state['mode'] in ('genlink', 'custom_selection') and getattr(forwarded, 'id', None) != state['channel'] and not text.startswith('https://t.me/c/'):
                # Consume before I/O: duplicate input cannot replay an ambiguous copy.
                self.state = None
                from .ingest import copy_into_archive, IngestError
                try:
                    mid = await copy_into_archive(self.ctx, client, message, state['channel'])
                    if state['mode'] == 'custom_selection' and mid in state['ids']:
                        raise IngestError('Archive returned a repeated message ID. No link issued; inspect the archive before restarting.')
                    if self.clock() >= state['expires']:
                        raise IngestError('Session expired after copying. No link issued; an archive copy may remain.')
                except IngestError as error:
                    await reply(message, str(error))
                    return
                except Exception as error:
                    logger.warning('#Errors FileStore archive copy unconfirmed (%s)', type(error).__name__)
                    await reply(message, 'Archive copy unconfirmed. No link issued. Inspect the archive before restarting /genlink; a copy may remain.')
                    return
                if state['mode'] == 'custom_selection':
                    state['ids'].append(mid)
                    state['seen'].add(message.id)
                    self.state = state
                    await reply(message, f"Collected {len(state['ids'])}/50. Send another message, /done or /cancel. Cancellation does not delete archived copies.")
                else:
                    state['ids'] = [mid]
                    await self.finish(client, message, state)
                return
            try:
                if getattr(forwarded, "id", None) != state["channel"]:
                    mid = int(archive_reference(text, state["channel"]))
                if type(mid) is not int or not 0 < mid < 2**31:
                    raise ValueError("Invalid archive message ID.")
                if state['mode'] == 'custom_selection' and mid in state['ids']:
                    raise ValueError('This archive message was already collected. Choose another or /done.')
                if state['mode'] != 'custom_selection' and state["ids"] and not 0 <= mid - state["ids"][0] < 50:
                    raise ValueError(
                        "Choose an ascending first-to-last range of at most 50 messages."
                    )
                if len(state["ids"]) >= 50:
                    raise ValueError("Batch limit reached. Send /done or /cancel.")
            except ValueError as error:
                await reply(message, str(error))
                return
            state["ids"].append(mid)
            if state['mode'] == 'custom_selection':
                state['seen'].add(message.id)
            if state["mode"] == "genlink" or (state["mode"] == "batch" and len(state["ids"]) == 2):
                await self.finish(client, message, state)
            else:
                await reply(
                    message,
                    "Send the LAST archive message or its link."
                    if state["mode"] == "batch"
                    else f"Archive message added ({len(state['ids'])}). Send the next, /done or /cancel.",
                )

    async def finish(self, client, message, state):
        # Clear before network calls: never replay link creation on duplicate input.
        self.state = None
        selection = ('ids ' + ' '.join(str(mid) for mid in state['ids']) if state['mode'] == 'custom_selection'
                     else f"{state['ids'][0]} {state['ids'][-1]}")
        proxy = SimpleNamespace(
            text=f"/custom_batch {selection}",
            from_user=message.from_user,
            chat=message.chat,
            sender_chat=None,
            reply=message.reply,
        )
        await self.generate(client, proxy)
