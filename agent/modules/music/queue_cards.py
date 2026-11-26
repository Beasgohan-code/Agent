"""Bounded queue-card ownership and native rich updates; no playback mutation."""

import secrets
import time
from collections import OrderedDict

from pyrogram.types import (
    InlineKeyboardMarkup as Keyboard,
)
from ...utils.rich import reply, edit
from ...ui.theme import Theme
from pyrogram.enums import ButtonStyle


class QueueCards:
    def __init__(self, *, clock=time.monotonic, theme=None):
        self.theme = theme if theme is not None else Theme()
        self.clock = clock
        self.cards = OrderedDict()

    def keyboard(self, token, page, pages):
        paging = []
        if page > 1:
            paging.append(self.theme.button('Previous', icon='back', callback_data=f'mqueue:{token}:{page - 1}'))
        if page < pages:
            paging.append(self.theme.button('Next', icon='arrow', callback_data=f'mqueue:{token}:{page + 1}', style=ButtonStyle.PRIMARY))
        controls = [self.theme.button('Refresh', icon='stats', callback_data=f'mqueue:{token}:{page}'),
                    self.theme.button('Close', icon='ban', callback_data=f'mqueue:{token}:close', style=ButtonStyle.DANGER)]
        return Keyboard(([paging] if paging else []) + [controls])

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
