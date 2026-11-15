"""Bounded queue-card ownership and native rich updates; no playback mutation."""

import secrets
import time
from collections import OrderedDict

from pyrogram.types import (
    InlineKeyboardButton as Button,
    InlineKeyboardMarkup as Keyboard,
)
from ...utils.rich import reply, edit


class QueueCards:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.cards = OrderedDict()

    def keyboard(self, token, page, pages):
        row = []
        if page > 1:
            row.append(Button("← Previous", callback_data=f"mqueue:{token}:{page - 1}"))
        row.append(Button("Refresh", callback_data=f"mqueue:{token}:{page}"))
        if page < pages:
            row.append(Button("Next →", callback_data=f"mqueue:{token}:{page + 1}"))
        return Keyboard([row, [Button("Close", callback_data=f"mqueue:{token}:close")]])

    def resolve(self, query, token):
        entry = self.cards.get(token)
        message = getattr(query, "message", None)
        if entry is None:
            return False
        chat, mid, uid, expires = entry
        if expires <= self.clock():
            self.cards.pop(token, None)
            return False
        return (
            getattr(getattr(message, "chat", None), "id", None) == chat
            and getattr(message, "id", None) == mid
            and getattr(getattr(query, "from_user", None), "id", None) == uid
        )

    async def send(self, message, body, page, pages, *, card=None):
        if card is not None:
            query, token = card
            await edit(query, body, reply_markup=self.keyboard(token, page, pages))
            return
        token = secrets.token_hex(8)
        sent = await reply(
            message, body, reply_markup=self.keyboard(token, page, pages)
        )
        mid = getattr(sent, "id", None)
        if type(mid) is int and mid > 0:
            self.cards[token] = (
                message.chat.id,
                mid,
                message.from_user.id,
                self.clock() + 600,
            )
            while len(self.cards) > 200:
                self.cards.popitem(last=False)
