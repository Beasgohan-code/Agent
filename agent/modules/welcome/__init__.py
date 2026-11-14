"""Welcome module — greetings for joins and farewells for leaves."""

from __future__ import annotations

import html
import logging
import re

from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.handlers import ChatMemberUpdatedHandler

from ...platform.manifest import PluginManifest
from ...utils.rich import reply
from ...ui.tables import kv_table, panel

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="welcome",
    name="Welcome",
    version="1.0.0",
    description="Welcome and goodbye messages driven by real membership changes.",
    commands=("setwelcome", "welcome", "goodbye"),
    permissions=("messages.read", "messages.send"),
    scope="group",
)

KINDS = ("welcome", "goodbye")
DEFAULT_WELCOME = "Welcome {mention} to {chat}!"


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def render(template: str, *, user, chat, count: int | None) -> str:
    """Fill the small, documented placeholder set — nothing dynamic is invented.

        The stored template is escaped first. Replies are sent with HTML parsing on,
        so an unescaped ``<`` in a greeting would either inject markup into the group
        or make Telegram reject the message outright. The only markup that reaches
        the chat is the mention link built below.
        
    """
    name = getattr(user, "first_name", None) or "there"
    mention = (
        f'<a href="tg://user?id={int(user.id)}">{html.escape(name)}</a>'
        if getattr(user, "id", None)
        else html.escape(name)
    )
    title = getattr(chat, "title", None) or "the group"
    values = {'mention': mention, 'name': html.escape(name), 'chat': html.escape(str(title)),
              'count': str(count) if count is not None else '?'}
    rendered = re.sub(r'\{(mention|name|chat|count)\}', lambda match: values[match[1]], html.escape(template or ''))
    if len(rendered.encode('utf-16-le')) // 2 > 4000:
        raise ValueError('Expanded greeting exceeds conservative Telegram size limit')
    return rendered


def membership(member):
    """Tri-state membership: unknown data must never fabricate a join/leave."""
    status = getattr(member, 'status', None)
    if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return True
    if status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        return False
    if status == ChatMemberStatus.RESTRICTED:
        value = getattr(member, 'is_member', None)
        return value if isinstance(value, bool) else None
    return None



async def _count(client, chat_id: int) -> int | None:
    try:
        return await client.get_chat_members_count(chat_id)
    except Exception:  # noqa: BLE001 - the count is a nicety, not a requirement
        return None


def watch(ctx):
    """React to real join/leave events."""

    async def on_update(client, update):
        try:
            chat = getattr(update, "chat", None)
            if chat is None or getattr(chat, "type", None) not in (
                ChatType.GROUP,
                ChatType.SUPERGROUP,
            ):
                return
            new = getattr(update, "new_chat_member", None)
            old = getattr(update, "old_chat_member", None)
            if new is None or old is None:
                return
            user = getattr(new, "user", None) or getattr(update, "from_user", None)
            if user is None:
                return

            was_member, is_member = membership(old), membership(new)
            joined = was_member is False and is_member is True
            left = was_member is True and is_member is False
            kind = "welcome" if joined else "goodbye" if left else None
            if kind is None:
                return

            greeting = ctx.chats.greeting(chat.id, kind)
            if not greeting["enabled"] or not greeting["text"]:
                return
            count = await _count(client, chat.id) if "{count}" in greeting["text"] else None
            await client.send_message(
                chat.id, render(greeting["text"], user=user, chat=chat, count=count), parse_mode=ParseMode.HTML
            )
        except Exception as error:  # watcher failure must not break the client
            logger.warning("welcome delivery unconfirmed (%s)", type(error).__name__)

    return on_update


def extra_handlers(ctx):
    return [ChatMemberUpdatedHandler(watch(ctx))]


def build(ctx):
    async def _guard(client, message) -> bool:
        from ..moderation import is_moderator
        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            await reply(message, 'Use your personal Telegram user identity to configure greetings.')
            return False

        if await is_moderator(client, message, need="can_change_info", owner_id=ctx.settings.owner_id):
            return True
        await reply(message, "Only chat administrators can change greetings.")
        return False

    async def setwelcome(client, message):
        if not await _guard(client, message):
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        text = parts[1].strip() if len(parts) == 2 else ""
        if not text:
            await reply(message, 
                "Usage: <code>/setwelcome Welcome {mention} to {chat}!</code>\n"
                "Placeholders: {mention} {name} {chat} {count}. The text is sent "
                "as plain text, so markup in it is shown, not applied."
            )
            return
        if len(text) > 1500:
            await reply(message, 'Greeting text is limited to 1500 characters; nothing was changed.')
            return
        ctx.chats.set_greeting(message.chat.id, "welcome", text)
        await reply(message, panel("Welcome updated", icon=ctx.theme.emoji("check"),
            lines=["Welcome message applied and enabled."],
            note="Group-local settings use background persistence. /welcome shows the current layout."))

    async def welcome(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        if len(args) > 2 or (len(args) == 2 and args[1].lower() not in ('on', 'off')):
            await reply(message, 'Usage: <code>/welcome [on|off]</code>. Set text with /setwelcome.')
            return
        if len(args) == 2:
            state = ctx.chats.toggle_greeting(
                message.chat.id, "welcome", args[1].lower() == "on"
            )
            await reply(message, 
                f"Welcome messages are now {'on' if state['enabled'] else 'off'}."
            )
            return
        current = ctx.chats.greeting(message.chat.id, "welcome")
        await reply(message, panel('Welcome studio', icon=ctx.theme.emoji('sparkles'),
            table=kv_table([('Status', 'on' if current['enabled'] else 'off'), ('Limit', '1500 characters')]),
            lines=['<b>Template</b>\n<code>' + html.escape(current['text']) + '</code>' if current['text'] else 'No greeting text set.'],
            note='Placeholders: {mention} {name} {chat} {count}. Templates are plain text; the mention is generated safely.',
            footer='/setwelcome text · /welcome on|off'))

    async def goodbye(client, message):
        if not await _guard(client, message):
            return
        args = _args(message)
        if len(args) > 2 and args[1].lower() in ('on', 'off'):
            await reply(message, 'Usage: <code>/goodbye on|off</code> without extra arguments.')
            return
        if len(args) == 2 and args[1].lower() in ("on", "off"):
            state = ctx.chats.toggle_greeting(
                message.chat.id, "goodbye", args[1].lower() == "on"
            )
            await reply(message, 
                f"Goodbye messages are now {'on' if state['enabled'] else 'off'}."
            )
            return
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        text = parts[1].strip() if len(parts) == 2 else ""
        if not text:
            current = ctx.chats.greeting(message.chat.id, "goodbye")
            await reply(message, 
                "<b>Goodbye message</b>\n"
                f"Status: {'on' if current['enabled'] else 'off'}\n"
                f"Text: {html.escape(current['text']) or '<i>not set</i>'}\n\n"
                "Set one with <code>/goodbye text</code>."
            )
            return
        if len(text) > 1500:
            await reply(message, 'Greeting text is limited to 1500 characters; nothing was changed.')
            return
        ctx.chats.set_greeting(message.chat.id, "goodbye", text)
        await reply(message, panel("Goodbye updated", icon=ctx.theme.emoji("check"),
            lines=["Goodbye message applied and enabled."], note="Group-local settings use background persistence."))

    return MANIFEST, {"setwelcome": setwelcome, "welcome": welcome, "goodbye": goodbye}
