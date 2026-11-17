"""Group management — the panel and the settings a real group needs.

Moderation (``agent.modules.moderation``) already answers *what happened to a
member*: warn, mute, kick, ban, purge. This module answers the other half of
running a group:

* ``/settings`` — one panel showing every per-group setting this bot actually
  enforces, read live from the chat store (nothing is decoration).
* ``/rules`` and ``/setrules`` — the group's rules, stored per group.
* ``/pin`` and ``/unpin`` — pinning, including ``/unpin all``.
* ``/admins`` — the group's administrators, read from Telegram.
* ``/warnlimit`` — how many warnings trigger an automatic action, and which one.
* ``/resetwarns`` — clear every warning a member has.
* ``/lockdown`` — restrict the group to administrators, and lift it again.

``/warnlimit`` is not a stored preference without effect: the value is read by
``/warn`` when it escalates, so the number shown in ``/settings`` is the number
that acts.
"""

from __future__ import annotations

import asyncio
import inspect
import html
import logging

from pyrogram.enums import ChatMemberStatus, ChatMembersFilter
from pyrogram.types import ChatPermissions

from ...platform.manifest import PluginManifest
from ...platform.admin_settings import denied
from ...platform.blocklists import operate as read_blocklist
from ...platform.service_cleaning import operate as read_cleaning
from .topics import COMMANDS as TOPIC_COMMANDS, build as build_topics
from .fullpromote import build as build_fullpromote
from .afk import build as build_afk, watch as watch_afk
from .details import COMMANDS as DETAIL_COMMANDS, build as build_details
from .admin import COMMANDS as ADMIN_COMMANDS, build as build_admin
from ...ui.tables import Table, kv_table, panel
from ..moderation import (
    DENIED,
    WARN_ACTIONS,
    is_moderator,
    parse_target,
    target_is_protected,
    warn_policy,
)
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    group_compatible=True,
    clone_compatible=True,
    slug="group",
    name="Group management",
    version="1.0.0",
    description="Group panel, rules, pinning, admin list, warn thresholds and lockdown.",
    commands=(
        "fullpromote", "afk", "settings", "rules", "setrules", "resetrules", "pin", "unpin",
        "admins", "warnlimit", "resetwarns", "lockdown", *ADMIN_COMMANDS, *TOPIC_COMMANDS, *DETAIL_COMMANDS,
    ),
    permissions=(
        "chats.read", "chats.restrict", "chats.pin", "messages.read", "messages.send",
    ),
    scope="group",
)

MAX_RULES = 3000
MAX_ADMIN_ROWS = 15

#: Nothing may be sent by ordinary members while a lockdown is on.
LOCKED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

#: Legacy open permissions (not used to restore a lockdown).
OPEN_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def _on_off(flag: object) -> str:
    return "on" if flag else "off"


def build(ctx):
    """Wire the group-management commands to the shared chat store."""

    from .plugin_panel import build as build_plugin_panel
    ctx.group_plugin_panel = build_plugin_panel(ctx)
    from ...platform import group_rules as rule_service
    from ...platform.group_trust import trusted_members
    from ...platform.group_filters import operate as read_filters
    from .controls import register, keyboard as management_keyboard
    register(ctx)

    async def _guard(client, message, need: str | None = None) -> bool:
        if await is_moderator(client, message, need=need, ctx=ctx):
            return True
        await denied(ctx, message, DENIED)
        return False

    async def _protected(client, message, target_id: int) -> bool:
        if await target_is_protected(client, message.chat.id, target_id):
            await reply(message, "I cannot act on an administrator or a target whose membership could not be verified. Action not attempted.")
            return True
        return False

    # -- /settings ---------------------------------------------------------

    async def settings(client, message):
        if not await _guard(client, message, need="can_change_info"):
            return
        chat_id = message.chat.id
        limit, action = warn_policy(ctx.chats, chat_id)
        from ..welcome import read_greeting
        try:
            from ...platform.antispam import read_policy
            policy = await read_policy(ctx, chat_id)
            greeting = await read_greeting(ctx, chat_id, "welcome")
            goodbye = await read_greeting(ctx, chat_id, "goodbye")
            rules = (await rule_service.read_rules(ctx, chat_id))["body"].strip()
            current_filters = await read_filters(ctx, chat_id)
            trusted = len(await trusted_members(ctx, chat_id))
            blocklist = await read_blocklist(ctx, chat_id)
            cleaning = await read_cleaning(ctx, chat_id)
        except Exception as error:
            logger.warning("Group settings state unavailable (%s)", type(error).__name__)
            await reply(message, "Group settings could not be loaded. Please try again shortly; no changes were made.")
            return
        # The log channel is switched at runtime by /setlog, so read the live
        # logbook rather than the value the process started with.
        logbook = getattr(ctx, "logbook", None)
        log_channel = (
            logbook.channel_id
            if logbook is not None and getattr(logbook, "channel_id", None) is not None
            else ctx.settings.log_channel
        )

        policy_state = "on" if any(
            policy.get(key)
            for key in ("flood_enabled", "duplicate_enabled", "links_enabled", "invites_enabled", "keywords_enabled")
        ) else "off"
        table = kv_table(
            [
                ("Group", str(chat_id)),
                ("Anti-spam", f"{policy_state} / {policy.get('action', 'warn')}"),
                ("Flood", f"{policy.get('flood_messages')} per {policy.get('flood_window_seconds')}s"),
                ("Links", "blocked" if policy.get("links_enabled") else "allowed"),
                ("Invites", "blocked" if policy.get("invites_enabled") else "allowed"),
                ("Keywords", str(len(policy.get("blocked_keywords") or []))),
                ("Blocklist", f"{len(blocklist['entries'])} / {blocklist['mode']}"),
                ("Service cleaning", ", ".join(cleaning) or "off"),
                ("Warn limit", f"{limit} -> {action}" if limit else "off"),
                ("Welcome", _on_off(greeting.get("enabled"))),
                ("Goodbye", _on_off(goodbye.get("enabled"))),
                ("Filters", str(len(current_filters))),
                ("Rules", f"{len(rules)} chars" if rules else "not set"),
                ("Approved", str(trusted)),
                ("Log channel", str(log_channel or "not set")),
            ]
        )
        await reply(message, 
            panel(
                "Group Management",
                icon=ctx.theme.emoji("gear"),
                subtitle="Protection, greetings and group tools in one place.",
                table=table,
                note=(
                    "Change them with <code>/antispam</code>, <code>/warnlimit</code>, "
                    "<code>/setrules</code>, <code>/setwelcome</code>, <code>/goodbye</code> "
                    "and <code>/lockdown</code>."
                ),
                footer="Administrators with the change-info right only.",
            ),
            reply_markup=management_keyboard(ctx) if getattr(ctx, "actions", None) is not None else None,
        )

    # -- /rules and /setrules ---------------------------------------------

    async def rules(client, message):
        chat_id = message.chat.id
        try:
            text = (await rule_service.read_rules(ctx, chat_id))["body"].strip()
        except rule_service.RulesError as error:
            await reply(message, str(error))
            return
        title = html.escape(getattr(message.chat, "title", None) or "This group")
        if not text:
            await reply(message, 
                panel(
                    "Rules",
                    icon=ctx.theme.emoji("shield"),
                    subtitle=f"<b>{title}</b> has no rules stored yet.",
                    note="An administrator can publish them with <code>/setrules &lt;text&gt;</code>.",
                )
            )
            return
        parts = list(rule_service.message_chunks(text))
        for index, part in enumerate(parts):
            await reply(message, panel(
                "Rules", icon=ctx.theme.emoji("shield"), subtitle=f"<b>{title}</b>",
                lines=[f"<blockquote>{_escaped_block(part)}</blockquote>"],
                footer=f"Part {index+1} of {len(parts)}" if len(parts) > 1 else "Set by an administrator of this group.",
            ))

    async def resetrules(client, message):
        if not await _guard(client, message, need="can_change_info"):
            return
        if len((getattr(message, 'text', '') or '').split()) != 1:
            await reply(message, 'Usage: <code>/resetrules</code> — clear rules in this group only.')
            return
        try:
            await rule_service.save_rules(ctx, message.chat.id, '', actor=message.from_user.id)
        except rule_service.RulesError as error:
            await reply(message, str(error))
            return
        await reply(message, 'Group rules cleared. Revision history retained.')

    async def setrules(client, message):
        if not await _guard(client, message, need="can_change_info"):
            return
        chat_id = message.chat.id
        parts = (getattr(message, "text", "") or "").split(maxsplit=1)
        body = parts[1].strip() if len(parts) > 1 else ""
        if not body:
            replied = getattr(message, "reply_to_message", None)
            body = (getattr(replied, "text", "") or "").strip() if replied else ""
        if not body:
            await reply(message, 
                "Usage: <code>/setrules &lt;text&gt;</code>, or reply to a message with "
                "<code>/setrules</code>. Use <code>/setrules clear</code> to remove them."
            )
            return
        if body.lower() == "clear":
            try:
                await rule_service.save_rules(ctx, chat_id, "", actor=message.from_user.id)
            except rule_service.RulesError as error:
                await reply(message, str(error))
                return
            await reply(message, "Group rules cleared.")
            return
        if len(body) > MAX_RULES:
            await reply(message, 
                f"Those rules are too long: {len(body)} characters, the limit is {MAX_RULES}."
            )
            return
        try:
            await rule_service.save_rules(ctx, chat_id, body, actor=message.from_user.id)
        except rule_service.RulesError as error:
            await reply(message, str(error))
            return
        await reply(message, 
            f"Group rules saved ({len(body)} characters). Members can read them with <code>/rules</code>."
        )

    # -- /pin and /unpin ---------------------------------------------------

    async def pin(client, message):
        if not await _guard(client, message, need="can_pin_messages"):
            return
        replied = getattr(message, "reply_to_message", None)
        if replied is None:
            await reply(message, "Reply to the message you want pinned with <code>/pin</code>.")
            return
        silent = "silent" in [a.lower() for a in _args(message)[1:]]
        try:
            await client.pin_chat_message(
                message.chat.id,
                replied.id,
                disable_notification=silent,
                both_sides=True,
            )
        except Exception as exc:  # noqa: BLE001 - Telegram's refusal reaches the user
            logger.exception("pin failed")
            await reply(message, f"Could not pin: {type(exc).__name__}. Check my pin rights.")
            return
        ctx.chats.log(
            message.chat.id, "pin", actor_id=message.from_user.id,
            reason=f"message {replied.id}",
        )
        await reply(message, 
            "Message pinned." + (" No notification was sent." if silent else "")
        )

    async def unpin(client, message):
        if not await _guard(client, message, need="can_pin_messages"):
            return
        args = [a.lower() for a in _args(message)[1:]]
        try:
            if args and args[0] == "all":
                await client.unpin_all_chat_messages(message.chat.id)
                ctx.chats.log(message.chat.id, "unpin:all", actor_id=message.from_user.id)
                await reply(message, "All pinned messages were unpinned.")
                return
            replied = getattr(message, "reply_to_message", None)
            await client.unpin_chat_message(
                message.chat.id, replied.id if replied is not None else 0
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("unpin failed")
            await reply(message, f"Could not unpin: {type(exc).__name__}. Check my pin rights.")
            return
        ctx.chats.log(message.chat.id, "unpin", actor_id=message.from_user.id)
        await reply(message, "Message unpinned.")

    # -- /admins -----------------------------------------------------------

    async def admins(client, message):
        rows: list[tuple[str, str, str]] = []
        extra = 0
        try:
            async for member in client.get_chat_members(
                message.chat.id, filter=ChatMembersFilter.ADMINISTRATORS
            ):
                user = getattr(member, "user", None)
                if user is None or getattr(getattr(member, "privileges", None), "is_anonymous", False):
                    continue
                if len(rows) >= MAX_ADMIN_ROWS:
                    extra += 1
                    continue
                role = (
                    "creator"
                    if getattr(member, "status", None) is ChatMemberStatus.OWNER
                    else "admin"
                )
                name = " ".join(
                    part
                    for part in (
                        getattr(user, "first_name", "") or "",
                        getattr(user, "last_name", "") or "",
                    )
                    if part
                ) or (getattr(user, "username", "") or "member")
                rows.append((role, name, str(user.id)))
        except Exception as exc:  # noqa: BLE001 - honest failure, not an empty list
            logger.exception("could not list administrators")
            await reply(message, 
                f"Could not read the administrator list: {type(exc).__name__}. "
                "I need to be an administrator to see it."
            )
            return
        if not rows:
            await reply(message, "No administrators were returned for this group.")
            return
        table = Table(
            headers=("Role", "Name", "ID"),
            rows=tuple(rows),
            aligns=("left", "left", "right"),
        )
        lines = [f"Plus {extra} more."] if extra else []
        await reply(message, 
            panel(
                "Administrators",
                icon=ctx.theme.emoji("shield"),
                table=table,
                lines=lines,
                footer="Read live from Telegram — nobody is cached.",
            )
        )

    # -- /warnlimit --------------------------------------------------------

    async def warnlimit(client, message):
        if not await _guard(client, message, need="can_change_info"):
            return
        chat_id = message.chat.id
        args = [a.lower() for a in _args(message)[1:]]
        if args:
            if args[0] in ("off", "0"):
                ctx.chats.put(chat_id, "warn_limit", 0)
            elif args[0].isdigit():
                ctx.chats.put(chat_id, "warn_limit", max(1, min(20, int(args[0]))))
            else:
                await reply(message, 
                    "Usage: <code>/warnlimit 3 [mute|kick|ban]</code> or <code>/warnlimit off</code>"
                )
                return
            if len(args) > 1:
                if args[1] not in WARN_ACTIONS:
                    await reply(message, 
                        f"Unknown action <code>{args[1]}</code>. Use one of: "
                        + ", ".join(WARN_ACTIONS)
                        + "."
                    )
                    return
                ctx.chats.put(chat_id, "warn_action", args[1])
            ctx.chats.log(
                chat_id, "warnlimit", actor_id=message.from_user.id, reason=" ".join(args)
            )

        limit, action = warn_policy(ctx.chats, chat_id)
        # "kick" + "d" is not a word.
        past = {"mute": "muted", "kick": "kicked", "ban": "banned"}.get(action, action)
        if not limit:
            body = (
                f"{ctx.theme.emoji('warn')} <b>Warnings do not escalate</b> in this group.\n"
                "Set a threshold with <code>/warnlimit 3</code>."
            )
        else:
            body = (
                f"{ctx.theme.emoji('warn')} At <b>{limit}</b> active warnings the member is "
                f"<b>{past}</b> automatically.\n"
                "Change it with <code>/warnlimit &lt;n&gt; [mute|kick|ban]</code>."
            )
        await reply(message, panel("Warn threshold", icon=ctx.theme.emoji("warn"), lines=[body]))

    # -- /resetwarns -------------------------------------------------------

    async def resetwarns(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to clear all their warnings.")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        cleared = await ctx.chats.aclear_all_warnings(message.chat.id, target_id)
        if not cleared:
            await reply(message, f"{mention} had no active warnings.")
            return
        ctx.chats.log(
            message.chat.id, "resetwarns", actor_id=message.from_user.id,
            target_id=target_id, reason=f"{cleared} cleared",
        )
        await reply(message, 
            f"<b>Warnings cleared</b>\nMember: {mention}\nCleared: {cleared}"
        )

    # -- /lockdown ---------------------------------------------------------

    lockdown_locks = {}

    async def lockdown(client, message):
        lock = lockdown_locks.setdefault(message.chat.id, asyncio.Lock())
        async with lock:
            await _lockdown(client, message)

    async def _lockdown(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        args = [a.lower() for a in _args(message)[1:]]
        if len(args) > 1 or (args and args[0] not in ("on", "lock", "off", "unlock", "open")):
            await reply(message, "Use /lockdown on or /lockdown off. No permissions were changed.")
            return
        locking = not (args and args[0] in ("off", "unlock", "open"))
        chat_id = message.chat.id
        active = ctx.chats.get(chat_id, "lockdown", False)
        saved = ctx.chats.get(chat_id, "lockdown_permissions")
        if locking and active:
            await reply(message, "Lockdown is already on; the original permissions are preserved.")
            return
        if not locking and not active:
            await reply(message, "Lockdown is already off; no permissions were changed.")
            return
        try:
            if locking:
                chat = await client.get_chat(chat_id)
                current = getattr(chat, "permissions", None)
                if current is None:
                    await reply(message, "Cannot read the current group permissions; nothing changed.")
                    return
                saved = {
                    key: value for key in inspect.signature(ChatPermissions).parameters
                    if isinstance(value := getattr(current, key, None), bool)
                }
                if not saved:
                    await reply(message, "Cannot read the current group permissions; nothing changed.")
                    return
                # Keep the baseline before contacting Telegram, so a failed or
                # interrupted request does not erase the only recovery record.
                ctx.chats.put(chat_id, "lockdown_permissions", saved)
                permissions = LOCKED_PERMISSIONS
            else:
                if not isinstance(saved, dict) or not saved:
                    await reply(message, "No saved pre-lockdown permissions. Restore them in Telegram's group settings; I will not open all permissions.")
                    return
                allowed = inspect.signature(ChatPermissions).parameters
                if any(k not in allowed or not isinstance(v, bool) for k, v in saved.items()):
                    await reply(message, "Saved permissions are invalid; no permissions were changed.")
                    return
                permissions = ChatPermissions(**saved)
            await client.set_chat_permissions(chat_id, permissions)
        except Exception as exc:  # noqa: BLE001
            logger.exception("lockdown failed")
            await reply(message, 
                f"Could not change group permissions: {type(exc).__name__}. "
                "I need the restrict-members right."
            )
            return
        ctx.chats.put(message.chat.id, "lockdown", locking)
        ctx.chats.log(
            message.chat.id, "lockdown" if locking else "unlock",
            actor_id=message.from_user.id,
        )
        if locking:
            body = (
                f"{ctx.theme.emoji('lock')} <b>Lockdown is on</b>\n"
                "Only administrators can send messages. Lift it with "
                "<code>/lockdown off</code>."
            )
        else:
            body = (
                f"{ctx.theme.emoji('check')} <b>Lockdown lifted</b>\n"
                "The group's pre-lockdown permissions were restored."
            )
        await reply(message, panel("Lockdown", icon=ctx.theme.emoji("lock"), lines=[body]))

    return MANIFEST, {
        **build_admin(ctx),
        **build_details(ctx),
        "afk": build_afk(ctx),
        "fullpromote": build_fullpromote(ctx),
        **build_topics(ctx),
        "settings": settings,
        "rules": rules,
        "setrules": setrules,
        "resetrules": resetrules,
        "pin": pin,
        "unpin": unpin,
        "admins": admins,
        "warnlimit": warnlimit,
        "resetwarns": resetwarns,
        "lockdown": lockdown,
    }


def _escaped_block(text: str) -> str:
    """Rule text as HTML, preserving line breaks inside the quote."""
    return "<br/>".join(html.escape(line) for line in text.splitlines())


def extra_handlers(ctx):
    from pyrogram import filters
    from pyrogram.handlers import MessageHandler
    return [MessageHandler(watch_afk(ctx),filters.group)]
