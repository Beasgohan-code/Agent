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
from ...platform.antispam import read_policy, change_policy
from ...platform.group_rules import read_rules
from ...platform.blocklists import operate as read_blocklist
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
            Button("Protection controls", callback_data="gmanage:protection:show"),
            Button("Group rules", callback_data="gmanage:rules:show"),
        ],
    ]
    rows.append([Button("Blocklist settings", callback_data="gmanage:blocklist:show")])
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
            parts = rest.split(":")
            protection = bool(
                parts
                and parts[0]
                in ("protection", "links", "invites", "flood", "duplicates")
            )
            need = "can_manage_chat" if protection else "can_change_info"
            # Deployment ownership never substitutes for Telegram group rights.
            if not await is_moderator(client, request, need=need):
                await query.answer(
                    "The required group-admin permission is missing.",
                    show_alert=True,
                )
                return
            parts = rest.split(":")
            if (
                len(parts) != 2
                or parts[0]
                not in (
                    "home",
                    "rules",
                    "blocklist",
                    "welcome",
                    "goodbye",
                    "protection",
                    "links",
                    "invites",
                    "flood",
                    "duplicates",
                )
                or parts[1] not in ("show", "on", "off")
            ):
                await query.answer(
                    "This control is no longer available.", show_alert=True
                )
                return
            kind, action = parts
            if kind == "blocklist":
                if action != "show":
                    await query.answer(
                        "Use the blocklist commands to change these settings.",
                        show_alert=True,
                    )
                    return
                state = await read_blocklist(ctx, chat.id)
                text = panel(
                    "Blocklist settings",
                    table=kv_table(
                        [
                            ("Triggers", str(len(state["entries"]))),
                            ("Action", state["mode"]),
                            ("Duration", f"{state['seconds']}s"),
                            ("Delete messages", "On" if state["delete"] else "Off"),
                        ]
                    ),
                    note="Use /blocklist to list triggers, /addblocklist to add a phrase or file: pattern, /blocklistmode to choose an action, and /blocklistdelete on|off to control deletion. Bulk removal requires the chat owner and confirmation.",
                )
                buttons = Keyboard(
                    [
                        [Button("Refresh", callback_data="gmanage:blocklist:show")],
                        [Button("Group Management", callback_data="gmanage:home:show")],
                    ]
                )
            elif kind == "rules":
                if action != "show":
                    await query.answer(
                        "Use /setrules to change rules.", show_alert=True
                    )
                    return
                state = await read_rules(ctx, chat.id)
                body = state["body"]
                preview = body[:1000]
                text = panel(
                    "Group rules",
                    table=kv_table(
                        [
                            ("Status", "Published" if body else "Not configured"),
                            ("Revision", str(state["version"])),
                        ]
                    ),
                    lines=[
                        "<blockquote>"
                        + html.escape(preview)
                        + ("…" if len(body) > 1000 else "")
                        + "</blockquote>"
                        if body
                        else "Add your group’s rules to help members get started."
                    ],
                    note="Publish with /setrules &lt;text&gt; or reply to a message with /setrules. Members can read all rules with /rules. /setrules clear removes the published text while retaining PostgreSQL revision history.",
                )
                buttons = Keyboard(
                    [
                        [
                            Button("Refresh", callback_data=f"{PREFIX}:rules:show"),
                            Button(
                                "Group Management", callback_data=f"{PREFIX}:home:show"
                            ),
                        ]
                    ]
                )
            elif protection:
                if kind == "protection" and action != "show":
                    await query.answer(
                        "Choose a specific protection switch.", show_alert=True
                    )
                    return
                if action != "show":
                    policy = await change_policy(ctx, chat.id, kind, action, actor=uid)
                else:
                    policy = await read_policy(ctx, chat.id)
                fields = [
                    ("links", "Link filtering", "links_enabled"),
                    ("invites", "Invite filtering", "invites_enabled"),
                    ("flood", "Flood protection", "flood_enabled"),
                    ("duplicates", "Duplicate protection", "duplicate_enabled"),
                ]
                text = panel(
                    "Group protection",
                    table=kv_table(
                        [
                            (label, "On" if policy[key] else "Off")
                            for _, label, key in fields
                        ]
                        + [
                            ("Action", policy["action"]),
                            ("Blocked phrases", str(len(policy["blocked_keywords"]))),
                        ]
                    ),
                    note="Switches apply only to this group. Staff and trusted members remain exempt. Use /antispam for thresholds, actions and blocked phrases.",
                )
                buttons = Keyboard(
                    [
                        [
                            Button(
                                f"{label} · {'Turn off' if policy[key] else 'Turn on'}",
                                callback_data=f"{PREFIX}:{name}:{'off' if policy[key] else 'on'}",
                            )
                        ]
                        for name, label, key in fields
                    ]
                    + [
                        [
                            Button(
                                "Refresh", callback_data=f"{PREFIX}:protection:show"
                            ),
                            Button(
                                "Group Management", callback_data=f"{PREFIX}:home:show"
                            ),
                        ]
                    ]
                )
            elif kind == "home":
                if action != "show":
                    await query.answer("Invalid overview action.", show_alert=True)
                    return
                states = [
                    await welcome.read_greeting(ctx, chat.id, k)
                    for k in ("welcome", "goodbye")
                ]
                current_rules = await read_rules(ctx, chat.id)
                blocklist = await read_blocklist(ctx, chat.id)
                text = panel(
                    "Group Management",
                    table=kv_table(
                        [
                            ("Welcome", "On" if states[0]["enabled"] else "Off"),
                            ("Goodbye", "On" if states[1]["enabled"] else "Off"),
                            (
                                "Blocklist",
                                f"{len(blocklist['entries'])} triggers / {blocklist['mode']}",
                            ),
                            (
                                "Rules",
                                "Configured"
                                if current_rules["body"]
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
