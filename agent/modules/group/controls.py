"""Group Management subpanels; every press checks current group rights."""

import html
import logging
from types import SimpleNamespace

from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.types import (
    InlineKeyboardButton as Button,
    InlineKeyboardMarkup as Keyboard,
)

from ...ui.tables import panel, kv_table
from ...utils.rich import edit
from ..moderation import is_moderator
from .. import welcome

logger = logging.getLogger(__name__)
PREFIX = "gmanage"


def keyboard(ctx):
    rows = [
        [
            Button("Welcome messages", callback_data="gmanage:welcome:show"),
            Button("Goodbye messages", callback_data="gmanage:goodbye:show"),
        ],
        [
            Button("Protection guide", callback_data="help:moderation"),
            Button("Rules & tools guide", callback_data="help:group-management"),
        ],
    ]
    if getattr(ctx, "group_plugin_panel", None) is not None:
        rows.append([Button("Optional plugins", callback_data="gplug:page:0")])
    rows.append([Button("Refresh overview", callback_data="gmanage:home:show")])
    return Keyboard(rows)


def register(ctx):
    router = getattr(ctx, "actions", None)
    if router is None or router.handles(PREFIX + ":x"):
        return

    async def press(client, query, rest):
        origin = getattr(query, "message", None)
        chat = getattr(origin, "chat", None)
        user = getattr(query, "from_user", None)
        try:
            uid = getattr(user, "id", None)
            if (
                getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or type(getattr(chat, "id", None)) is not int
                or chat.id >= 0
                or type(uid) is not int
                or uid <= 0
            ):
                await query.answer(
                    "Use these controls as yourself inside the group.", show_alert=True
                )
                return
            request = SimpleNamespace(chat=chat, from_user=user)
            # Deployment ownership never substitutes for Telegram group rights.
            if not await is_moderator(client, request, need="can_change_info"):
                await query.answer(
                    "Group-admin permission to change group info is required.",
                    show_alert=True,
                )
                return
            parts = rest.split(":")
            if (
                len(parts) != 2
                or parts[0] not in ("home", "welcome", "goodbye")
                or parts[1] not in ("show", "on", "off")
            ):
                await query.answer(
                    "This control is no longer available.", show_alert=True
                )
                return
            kind, action = parts
            if kind == "home":
                if action != "show":
                    await query.answer("Invalid overview action.", show_alert=True)
                    return
                states = [
                    await welcome.read_greeting(ctx, chat.id, k)
                    for k in ("welcome", "goodbye")
                ]
                text = panel(
                    "Group Management",
                    table=kv_table(
                        [
                            ("Welcome", "On" if states[0]["enabled"] else "Off"),
                            ("Goodbye", "On" if states[1]["enabled"] else "Off"),
                            (
                                "Rules",
                                "Configured"
                                if ctx.chats.get(chat.id, "rules", "")
                                else "Not configured",
                            ),
                        ]
                    ),
                    note="One included suite. Configure greetings here or open protection and group tools below.",
                )
                buttons = keyboard(ctx)
            else:
                state = await welcome.read_greeting(ctx, chat.id, kind)
                if action == "on" and not state["text"].strip():
                    command = "/setwelcome" if kind == "welcome" else "/goodbye"
                    await query.answer(
                        f"Add a message with {command} <text> before enabling it.",
                        show_alert=True,
                    )
                    return
                if action != "show":
                    state = await welcome.toggle_greeting(
                        ctx, chat.id, kind, action == "on"
                    )
                command = "/setwelcome" if kind == "welcome" else "/goodbye"
                text = panel(
                    kind.title() + " messages",
                    table=kv_table(
                        [
                            ("Status", "On" if state["enabled"] else "Off"),
                            (
                                "Message",
                                "Configured" if state["text"] else "Not configured",
                            ),
                        ]
                    ),
                    lines=[
                        "<b>Message template</b>\n<code>"
                        + html.escape(state["text"])
                        + "</code>"
                        if state["text"]
                        else "No message has been added yet."
                    ],
                    note=f"Use <code>{command} &lt;text&gt;</code> to edit the message. Turning it off keeps your template.",
                )
                rows = [
                    [
                        Button(
                            "Turn off" if state["enabled"] else "Turn on",
                            callback_data=f"{PREFIX}:{kind}:{'off' if state['enabled'] else 'on'}",
                            style=ButtonStyle.PRIMARY,
                        )
                    ],
                    [
                        Button("Refresh", callback_data=f"{PREFIX}:{kind}:show"),
                        Button("Group Management", callback_data=f"{PREFIX}:home:show"),
                    ],
                ]
                buttons = Keyboard(rows)
            await edit(query, text, reply_markup=buttons)
            await query.answer("Updated." if action != "show" else None)
        except Exception as error:
            logger.warning(
                "Group control result unconfirmed (%s)", type(error).__name__
            )
            await query.answer(
                "Update not confirmed. Refresh to check the current state.",
                show_alert=True,
            )

    router.register(PREFIX, press)
