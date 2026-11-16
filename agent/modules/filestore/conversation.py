"""Bounded private archive conversations matching the reviewed prompt sequence."""

import asyncio
import time
from types import SimpleNamespace

from ...utils.rich import reply
from .channel_links import archive_reference, private


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
                ids=[],
                expires=self.clock() + 300,
                channel=self.ctx.settings.storage_channel,
            )
        text = (
            "Forward ONE message from this bot’s configured archive, or send its private Telegram link."
            if mode == "genlink" else
            "Send or forward the FIRST archive message, or its private Telegram link."
            if mode == "batch"
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
                    message, "Archive link creation cancelled. No link created."
                )
                return
            if text.startswith("/") and command != "/done":
                return
            if (
                self.clock() >= state["expires"]
                or self.ctx.settings.storage_channel != state["channel"]
            ):
                self.state = None
                await reply(
                    message,
                    "Archive session expired or configuration changed. Start again; no link created.",
                )
                return
            if command == "/done":
                if state["mode"] != "custom_batch" or not state["ids"]:
                    await reply(
                        message,
                        "No custom batch ready. Send an archive message first, or /cancel.",
                    )
                    return
                await self.finish(client, message, state)
                return
            forwarded = getattr(message, "forward_from_chat", None)
            mid = getattr(message, "forward_from_message_id", None)
            try:
                if getattr(forwarded, "id", None) != state["channel"]:
                    mid = int(archive_reference(text, state["channel"]))
                if type(mid) is not int or not 0 < mid < 2**31:
                    raise ValueError("Invalid archive message ID.")
                if state["ids"] and not 0 <= mid - state["ids"][0] < 50:
                    raise ValueError(
                        "Choose an ascending first-to-last range of at most 50 messages."
                    )
                if len(state["ids"]) >= 50:
                    raise ValueError("Batch limit reached. Send /done or /cancel.")
            except ValueError as error:
                await reply(message, str(error))
                return
            state["ids"].append(mid)
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
        proxy = SimpleNamespace(
            text=f"/custom_batch {state['ids'][0]} {state['ids'][-1]}",
            from_user=message.from_user,
            chat=message.chat,
            sender_chat=None,
            reply=message.reply,
        )
        await self.generate(client, proxy)
