"""Moderation — the group commands, and the rules that keep them honest.

Two deliberate rules, both to avoid fake behaviour:

* every destructive command verifies the caller's admin rights **and** that the
  target is not an administrator before it calls Telegram;
* ``/antispam`` stores a policy that is actually enforced — the same module
  ships the watcher that applies it, so the settings are not decoration.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from functools import wraps
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from pyrogram import filters as tg_filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import RPCError, FloodWait
from pyrogram.handlers import MessageHandler
from pyrogram.types import ChatPermissions

from .blocklists import COMMANDS as BLOCKLIST_COMMANDS, build as build_blocklists, enforce as enforce_blocklist
from ...platform.blocklists import history as blocklist_history, BlocklistError
from .restrictions import COMMANDS as RESTRICTION_COMMANDS, build as build_restrictions
from .antiflood import COMMANDS as FLOOD_COMMANDS, build as build_antiflood, watch as watch_antiflood
from ...platform.group_rules import rules_history, RulesError
from ...platform.restriction_cases import history as restriction_history, CaseError
from ...platform.admin_settings import options as admin_options, denied, AdminStateError
from ...platform.group_trust import trusted_members, trust_history, TrustError
from ...platform.antispam import read_policy, change_policy, policy_history, PolicyError
from ...platform.chats import SPAM_ACTIONS
from ...platform.manifest import PluginManifest
from ...ui.tables import Table, kv_table, panel
from ...utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="moderation",
    name="Moderation",
    version="1.0.0",
    description="Warn, mute, kick, ban, purge and per-group anti-spam, with an audit trail.",
    commands=(
        "warn", "warnings", "warns", "unwarn", "mute", "unmute", "kick", "ban",
        "unban", "purge", "note", "approve", "unapprove", "approval", "approved", "antispam", "modlog", *FLOOD_COMMANDS, *RESTRICTION_COMMANDS, *BLOCKLIST_COMMANDS,
    ),
    permissions=("messages.read", "messages.delete", "chats.restrict", "chats.ban"),
    scope="group",
)

DENIED = "You need moderator rights to do that."
DEFAULT_MUTE_SECONDS = 600
#: Warnings escalate at this threshold unless a group sets its own.
DEFAULT_WARN_LIMIT = 3
DEFAULT_WARN_ACTION = "mute"
WARN_ACTIONS = ("mute", "kick", "ban")
MAX_PURGE = 100
PURGE_CONFIRM_TTL = 4.0

#: Nothing allowed: the restriction Telegram applies to a muted member.
MUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


# -- argument parsing -------------------------------------------------------


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(name or "member")}</a>'


def parse_target(message) -> tuple[int, str] | None:
    """Resolve the member a command is about: a reply, or a numeric id."""
    replied = getattr(message, "reply_to_message", None)
    user = getattr(replied, "from_user", None) if replied is not None else None
    if user is not None:
        return int(user.id), _mention(user.id, getattr(user, "first_name", "member"))
    args = _args(message)
    if len(args) > 1:
        candidate = args[1].lstrip("@")
        if candidate.lstrip("-").isdigit():
            return int(candidate), f"<code>{candidate}</code>"
    return None


def parse_duration(args: list[str], default: int = DEFAULT_MUTE_SECONDS) -> int:
    """``30s``/``10m``/``2h``/``1d`` or a bare number of minutes."""
    if len(args) < 2:
        return default
    token = args[1].lower()
    multiplier = 60
    for suffix, factor in (("s", 1), ("m", 60), ("h", 3600), ("d", 86400)):
        if token.endswith(suffix):
            multiplier, token = factor, token[:-1]
            break
    try:
        return max(1, int(token) * multiplier)
    except ValueError:
        return default


def duration_label(seconds: int) -> str:
    for suffix, factor in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= factor and seconds % factor == 0:
            return f"{seconds // factor}{suffix}"
    return f"{seconds}s"


def warn_policy(chats, chat_id: int) -> tuple[int, str]:
    """(limit, action) for a group. A limit of 0 disables escalation."""
    limit = chats.get(chat_id, "warn_limit", DEFAULT_WARN_LIMIT)
    action = chats.get(chat_id, "warn_action", DEFAULT_WARN_ACTION)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_WARN_LIMIT
    if action not in WARN_ACTIONS:
        action = DEFAULT_WARN_ACTION
    return max(0, limit), action


def _reason(message, *, skip_target: bool) -> str:
    """Everything after the command (and the id, when one was passed)."""
    args = _args(message)
    rest = args[1:]
    if skip_target and rest and rest[0].lstrip("@").lstrip("-").isdigit():
        rest = rest[1:]
    return " ".join(rest).strip()[:400] or "no reason given"


# -- permission helpers -----------------------------------------------------


async def _member_of(client, chat_id: int, user_id: int):
    try:
        return await client.get_chat_member(chat_id, user_id)
    except Exception:  # noqa: BLE001 - unknown/absent members are normal
        return None


async def is_moderator(client, message, *, need: str | None = None, owner_id: int | None = None, ctx=None) -> bool:
    """True when the caller may act here.

        The bot owner always may; an administrator may when they hold the specific
        privilege the command needs (Telegram grants exactly these).
        
    """
    sender = getattr(message, "sender_chat", None)
    if sender is not None:
        if getattr(message, "from_user", None) is None:
            return False  # downstream audit/mutation paths require a sender identity
        if getattr(sender, "id", None) != getattr(getattr(message, "chat", None), "id", None):
            return False  # linked channels are not anonymous group administrators
        context = ctx or getattr(client, "agent_context", None)
        if context is None:
            return False
        try:
            return bool((await admin_options(context, message.chat.id))["anonadmin"])
        except AdminStateError:
            return False
    user = getattr(message, "from_user", None)
    if user is None:
        return False
    if owner_id is not None and int(user.id) == int(owner_id):
        return True
    member = await _member_of(client, message.chat.id, user.id)
    if member is None:
        return False
    status = getattr(member, "status", None)
    if status is ChatMemberStatus.OWNER:
        return True
    if status is not ChatMemberStatus.ADMINISTRATOR:
        return False
    if need is None:
        return True
    privileges = getattr(member, "privileges", None)
    return bool(privileges is not None and getattr(privileges, need, False))


async def target_is_protected(client, chat_id: int, target_id: int) -> bool:
    """Unknown membership is protected too: lookup failure is not consent."""
    if not isinstance(target_id, int) or isinstance(target_id, bool) or target_id <= 0:
        return True
    member = await _member_of(client, chat_id, target_id)
    status = getattr(member, "status", None)
    known = (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED,
             ChatMemberStatus.BANNED, ChatMemberStatus.LEFT)
    return status not in known


class PartialKickError(RuntimeError):
    """Ban was confirmed, but the unban request was not confirmed."""


async def kick_member(client, ctx, chat_id, target_id, *, actor_id=None, source="manual", confirm=False):
    """Use one recovery path for every kick; never retry the ban blindly."""
    banned = await client.ban_chat_member(chat_id, target_id)
    if confirm and banned is not True:
        raise RuntimeError("Kick ban was not confirmed.")
    try:
        unbanned = await client.unban_chat_member(chat_id, target_id)
        if confirm and unbanned is not True:
            raise RuntimeError("Kick unban was not confirmed.")
    except Exception as exc:
        ctx.chats.log(
            chat_id, "kick:incomplete", actor_id=actor_id, target_id=target_id,
            reason=f"{source}: ban confirmed; unban unconfirmed ({type(exc).__name__})",
        )
        delay = f" Wait {int(exc.value)} seconds before retrying." if isinstance(exc, FloodWait) else ""
        raise PartialKickError(
            f"Kick incomplete: the ban succeeded, but unban was not confirmed "
            f"({type(exc).__name__}). Member {int(target_id)} may still be banned."
            f"{delay} An administrator can check and use <code>/unban {int(target_id)}</code>."
        ) from exc


async def escalate_warning(client, ctx, message, target_id: int, action: str) -> str:
    """Apply the group's warn action. Returns a line for the report.

        A failure is reported, never swallowed: if the bot lacks the right to mute,
        saying "warned, muted" would be a lie.
        
    """
    chat_id = message.chat.id
    if await target_is_protected(client, chat_id, target_id):
        return "Escalation not attempted: target is protected or membership could not be verified."
    try:
        if action == "mute":
            await client.restrict_chat_member(
                chat_id,
                target_id,
                MUTE_PERMISSIONS,
                until_date=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_MUTE_SECONDS),
            )
            outcome = f"muted for {duration_label(DEFAULT_MUTE_SECONDS)}"
        elif action == "kick":
            await kick_member(client, ctx, chat_id, target_id, source="warnlimit")
            outcome = "kicked"
        else:
            await client.ban_chat_member(chat_id, target_id)
            outcome = "banned"
    except PartialKickError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - the moderator needs the real reason
        logger.exception("warn escalation failed")
        return f"Escalation failed: {type(exc).__name__}. Check my rights."
    ctx.chats.log(
        chat_id, f"warnlimit:{action}", actor_id=None, target_id=target_id,
        reason="warning threshold reached",
    )
    return f"Threshold reached: member {outcome}."


# -- anti-spam enforcement --------------------------------------------------

_INVITE_RE = re.compile(
    r"(?:t\.me/(?:joinchat/|\+)|telegram\.me/(?:joinchat/|\+)|telegram\.dog/)", re.IGNORECASE
)
_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


class _Recent:
    """Per-member message history, in memory only — chat content is not stored."""

    def __init__(self) -> None:
        self._seen: dict[tuple[int, int], deque] = defaultdict(deque)

    def note(self, chat_id: int, user_id: int, text: str, *, window: float) -> tuple[int, int]:
        """Record a message; return (messages in window, repeats of this text)."""
        now = time.monotonic()
        bucket = self._seen[(chat_id, user_id)]
        bucket.append((now, text))
        while bucket and now - bucket[0][0] > max(window, 60.0):
            bucket.popleft()
        in_window = sum(1 for stamp, _ in bucket if now - stamp <= window)
        repeats = sum(1 for _, body in bucket if body == text)
        return in_window, repeats

    def clear(self, chat_id: int, user_id: int) -> None:
        self._seen.pop((chat_id, user_id), None)


def _violation(policy: dict, text: str, in_window: int, repeats: int) -> str | None:
    if policy.get("links_enabled") and _LINK_RE.search(text):
        return "link"
    if policy.get("invites_enabled") and _INVITE_RE.search(text):
        return "invite"
    if policy.get("keywords_enabled"):
        lowered = text.lower()
        for keyword in policy.get("blocked_keywords") or []:
            if keyword and keyword.lower() in lowered:
                return "keyword"
    if policy.get("duplicate_enabled") and repeats >= int(policy.get("duplicate_threshold", 3)):
        return "duplicate"
    if policy.get("flood_enabled") and in_window > int(policy.get("flood_messages", 7)):
        return "flood"
    return None


async def _punish(client, ctx, message, action: str, *, policy: dict) -> None:
    chat_id = message.chat.id
    user_id = int(message.from_user.id)
    if action in ("delete", "warn", "mute", "kick", "ban"):
        try:
            await message.delete()
        except Exception:  # noqa: BLE001 - already gone is fine
            pass
    if action == "warn":
        ctx.chats.add_warning(chat_id, user_id, moderator_id=0, reason="anti-spam")
        await reply(message, 
            f"Anti-spam: {_mention(user_id, getattr(message.from_user, 'first_name', 'member'))} "
            f"warned. Warnings: {ctx.chats.active_warning_count(chat_id, user_id)}"
        )
    elif action == "mute":
        await client.restrict_chat_member(
            chat_id,
            user_id,
            MUTE_PERMISSIONS,
            until_date=datetime.now(timezone.utc) + timedelta(seconds=int(policy.get("mute_seconds", 300))),
        )
        await reply(message, f"Anti-spam: member muted for {policy.get('mute_seconds', 300)}s.")
    elif action == "kick":
        await kick_member(client, ctx, chat_id, user_id, source="antispam")
        await reply(message, "Anti-spam: member kicked.")
    elif action == "ban":
        await client.ban_chat_member(chat_id, user_id)
        await reply(message, "Anti-spam: member banned.")


def watch(ctx):
    """The message watcher that makes ``/antispam`` settings mean something."""

    recent = _Recent()

    async def on_message(client, message):
        try:
            chat = getattr(message, "chat", None)
            user = getattr(message, "from_user", None)
            if await enforce_blocklist(ctx, client, message):
                return
            text = (getattr(message, "text", "") or "").strip()
            if chat is None or user is None or not text or text.startswith("/"):
                return
            if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
                return
            policy = await read_policy(ctx, chat.id) if ctx.chats else {}
            if not any(
                policy.get(key)
                for key in ("flood_enabled", "duplicate_enabled", "links_enabled", "invites_enabled", "keywords_enabled")
            ):
                return
            if user.id in await trusted_members(ctx, chat.id):
                return
            in_window, repeats = recent.note(
                chat.id,
                user.id,
                text,
                window=float(policy.get("flood_window_seconds", 8)),
            )
            violation = _violation(policy, text, in_window, repeats)
            if violation is None:
                return
            if await is_moderator(client, message, owner_id=ctx.settings.owner_id):
                return  # staff are never auto-punished
            action = str(policy.get("action", "warn")).lower()
            if action not in SPAM_ACTIONS:
                action = "warn"
            if await target_is_protected(client, chat.id, user.id):
                return
            recent.clear(chat.id, user.id)
            await _punish(client, ctx, message, action, policy=policy)
            ctx.chats.log(
                chat.id, f"antispam:{action}", actor_id=None, target_id=int(user.id), reason=violation
            )
        except PartialKickError as exc:
            try:
                await reply(message, str(exc))
            except Exception:
                logger.exception("Could not send partial-kick recovery notice.")
        except Exception:  # noqa: BLE001 - a watcher must never break the client
            import logging

            logging.getLogger(__name__).exception("anti-spam watcher failed")

    return on_message


def extra_handlers(ctx):
    """The anti-spam watcher, registered by the bot in its own handler group."""
    return [MessageHandler(watch(ctx), tg_filters.group), MessageHandler(watch_antiflood(ctx), tg_filters.group)]


# -- handlers ---------------------------------------------------------------


def build(ctx):
    """Wire the moderation commands to this repository's shared state."""

    async def _guard(client, message, need: str | None = None) -> bool:
        if await is_moderator(client, message, need=need, owner_id=ctx.settings.owner_id, ctx=ctx):
            return True
        await denied(ctx, message, DENIED)
        return False

    async def _protected(client, message, target_id: int) -> bool:
        if await target_is_protected(client, message.chat.id, target_id):
            await reply(message, "I cannot act on an administrator or a target whose membership could not be verified. Action not attempted.")
            return True
        return False

    async def warn(client, message):
        if not await _guard(client, message):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member or pass their id: <code>/warn 123 [reason]</code>")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        reason = _reason(message, skip_target=True)
        count = ctx.chats.add_warning(
            message.chat.id, target_id, moderator_id=message.from_user.id, reason=reason
        )
        ctx.chats.log(
            message.chat.id, "warn", actor_id=message.from_user.id, target_id=target_id, reason=reason
        )
        limit, action = warn_policy(ctx.chats, message.chat.id)
        escalation = ""
        if limit and count >= limit:
            escalation = "\n" + await escalate_warning(client, ctx, message, target_id, action)
        await reply(message, 
            f"<b>Warning issued</b>\nMember: {mention}\nWarnings: {count}\n"
            f"Reason: {html.escape(reason)}{escalation}"
        )

    async def warnings(client, message):
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to inspect their warnings.")
            return
        target_id, mention = target
        rows = ctx.chats.warnings_of(message.chat.id, target_id)
        note = ctx.chats.note_of(message.chat.id, target_id)
        try:
            trusted = target_id in await trusted_members(ctx, message.chat.id)
        except TrustError as error:
            await reply(message, str(error))
            return
        limit, action = warn_policy(ctx.chats, message.chat.id)
        rows_out = tuple(
            (
                str(index),
                warning.get("reason", "no reason"),
                str(warning.get("by") or "-"),
                time.strftime("%d %b %H:%M", time.gmtime(warning.get("at", 0))),
            )
            for index, warning in enumerate(reversed(rows[-10:]), 1)
        )
        lines = [f"Member: {mention} — <b>{len(rows)}</b> active warning(s)."]
        if limit:
            lines.append(
                f"Escalates at <b>{limit}</b> warnings ({action})."
            )
        else:
            lines.append("Warnings do not escalate in this group.")
        if note:
            lines.append(f"Note: {html.escape(note)}")
        if trusted:
            lines.append("Approved: yes")
        table = Table(
            headers=("#", "Reason", "By", "When"),
            rows=rows_out,
            aligns=("right", "left", "right", "left"),
            total_width=52,
        ) if rows_out else None
        if table is None:
            lines.append("No active warnings.")
        await reply(message, 
            panel(
                "Warnings",
                icon=ctx.theme.emoji("warn"),
                lines=lines,
                table=table,
                footer="<code>/unwarn</code> clears one, <code>/resetwarns</code> clears all.",
            )
        )

    async def unwarn(client, message):
        if not await _guard(client, message):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to clear a warning.")
            return
        target_id, mention = target
        if not ctx.chats.clear_warning(message.chat.id, target_id):
            await reply(message, "That member has no active warnings.")
            return
        ctx.chats.log(
            message.chat.id, "unwarn", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, f"<b>Warning cleared</b>\nMember: {mention}")

    async def mute(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member: <code>/mute 10m reason</code>")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        seconds = parse_duration(_args(message))
        await client.restrict_chat_member(
            message.chat.id,
            target_id,
            MUTE_PERMISSIONS,
            until_date=datetime.now(timezone.utc) + timedelta(seconds=seconds),
        )
        ctx.chats.log(
            message.chat.id, "mute", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, 
            f"<b>Member muted</b>\nMember: {mention}\nDuration: {duration_label(seconds)}"
        )

    async def unmute(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to unmute them.")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        chat = await client.get_chat(message.chat.id)
        permissions = getattr(chat, "permissions", None)
        if permissions is None:
            await reply(message, "Cannot read the group's current permissions; no member permissions were changed.")
            return
        await client.restrict_chat_member(message.chat.id, target_id, permissions)
        ctx.chats.log(
            message.chat.id, "unmute", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, f"<b>Member unmuted</b>\nMember: {mention}")

    async def kick(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to kick them.")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        await kick_member(
            client, ctx, message.chat.id, target_id,
            actor_id=message.from_user.id, source="manual",
        )
        ctx.chats.log(
            message.chat.id, "kick", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, f"<b>Member kicked</b>\nMember: {mention}")

    async def ban(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member or pass an id to ban them.")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        reason = _reason(message, skip_target=True)
        await client.ban_chat_member(message.chat.id, target_id)
        ctx.chats.log(
            message.chat.id, "ban", actor_id=message.from_user.id, target_id=target_id, reason=reason
        )
        await reply(message, 
            f"<b>Member banned</b>\nMember: {mention}\nReason: {html.escape(reason)}"
        )

    async def unban(client, message):
        if not await _guard(client, message, need="can_restrict_members"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Pass the user id to unban: <code>/unban 123456</code>")
            return
        target_id, mention = target
        if await _protected(client, message, target_id):
            return
        await client.unban_chat_member(message.chat.id, target_id)
        ctx.chats.log(
            message.chat.id, "unban", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, f"<b>Member unbanned</b>\nMember: {mention}")

    async def purge(client, message):
        if not await _guard(client, message, need="can_delete_messages"):
            return
        args = _args(message)
        count = min(int(args[1]), MAX_PURGE) if len(args) > 1 and args[1].isdigit() else 10
        base = getattr(message, "id", None) or getattr(message, "message_id", 0)
        ids = [base - offset for offset in range(1, count + 1) if base - offset > 0]
        deleted = 0
        for message_id in ids:
            try:
                await client.delete_messages(message.chat.id, message_id)
                deleted += 1
            except Exception:  # noqa: BLE001 - already deleted / too old
                continue
        ctx.chats.log(
            message.chat.id, "purge", actor_id=message.from_user.id, reason=f"{deleted} removed"
        )
        confirmation = await reply(message, 
            f"<b>Purged</b>\nMessages removed: {deleted}\nOf requested: {count}"
        )
        if PURGE_CONFIRM_TTL and confirmation is not None:
            await asyncio.sleep(PURGE_CONFIRM_TTL)
            try:
                await confirmation.delete()
            except Exception:  # noqa: BLE001
                pass

    async def note(client, message):
        if not await _guard(client, message, need="can_manage_chat"):
            return
        target = parse_target(message)
        if target is None:
            await reply(message, "Reply to a member to attach a note.")
            return
        target_id, mention = target
        args = _args(message)
        text = " ".join(args[2:]).strip() if len(args) > 2 else ""
        if not text:
            await reply(message, "Provide the note text after the id.")
            return
        ctx.chats.set_note(message.chat.id, target_id, text)
        ctx.chats.log(
            message.chat.id, "note", actor_id=message.from_user.id, target_id=target_id
        )
        await reply(message, f"<b>Note saved</b>\nMember: {mention}")

    async def approval_command(client, message, desired=None, listing=False):
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        if (getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or getattr(message, "sender_chat", None) is not None
                or type(getattr(user, "id", None)) is not int or user.id <= 0):
            await reply(message, "Use approval commands as yourself inside a group.")
            return
        if not await is_moderator(client, message, need="can_manage_chat"):
            await denied(ctx, message, DENIED)
            return
        args = _args(message)
        try:
            if listing:
                if len(args) > 2 or (len(args) == 2 and (not args[1].isascii() or not args[1].isdecimal() or len(args[1]) > 8 or int(args[1]) < 1)):
                    await reply(message, "Usage: <code>/approved [page]</code>")
                    return
                members = sorted(await trusted_members(ctx, chat.id))
                page = int(args[1]) if len(args) == 2 else 1
                pages = max(1, (len(members) + 19) // 20)
                if page > pages:
                    await reply(message, f"Choose an approvals page from 1 to {pages}.")
                    return
                await reply(message, panel("Approved members", table=Table(
                    headers=("Member ID",), rows=tuple((str(uid),) for uid in members[(page-1)*20:page*20])),
                    lines=[] if members else ["No approved members in this group."],
                    footer=f"Page {page}/{pages} · /approved [page]",
                    note="Approved members are exempt from automatic anti-spam actions, not manual moderation."))
                return
            if len(args) > 2:
                await reply(message, "Reply to a member or provide one numeric member ID.")
                return
            target = parse_target(message)
            if target is None:
                await reply(message, "Reply to a member or provide their numeric ID.")
                return
            target_id, mention = target
            if not 0 < target_id < 2**63:
                await reply(message, "Provide a valid personal member ID.")
                return
            members = await trusted_members(ctx, chat.id, toggle=target_id if desired is not None else None,
                                           actor=user.id, approved=desired)
            state = "approved" if target_id in members else "not approved"
            await reply(message, f"<b>Member {state}</b>\nMember: {mention}")
        except TrustError as error:
            await reply(message, str(error))

    async def approve(client, message):
        await approval_command(client, message, desired=True)

    async def unapprove(client, message):
        await approval_command(client, message, desired=False)

    async def approval(client, message):
        await approval_command(client, message)

    async def approved(client, message):
        await approval_command(client, message, listing=True)

    async def antispam(client, message):
        chat = getattr(message, "chat", None)
        if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await reply(message, "Anti-spam settings are per group.")
            return
        if not await is_moderator(client, message, need="can_manage_chat"):
            await denied(ctx, message, DENIED)
            return
        args = _args(message)[1:]
        try:
            if args:
                policy = await change_policy(ctx, chat.id, args[0].lower(),
                    " ".join(args[1:]).lower() if len(args) > 1 else None,
                    actor=message.from_user.id)
            else:
                policy = await read_policy(ctx, chat.id)
        except PolicyError as error:
            await reply(message, str(error))
            return
        keywords = policy.get("blocked_keywords") or []
        table = kv_table(
            [
                ("Flood", f"{policy['flood_messages']} per {policy['flood_window_seconds']}s "
                          f"({'on' if policy['flood_enabled'] else 'off'})"),
                ("Duplicates", f"threshold {policy['duplicate_threshold']} "
                               f"({'on' if policy['duplicate_enabled'] else 'off'})"),
                ("Links", "blocked" if policy["links_enabled"] else "allowed"),
                ("Invites", "blocked" if policy["invites_enabled"] else "allowed"),
                ("Keywords", ", ".join(keywords) if keywords else "none"),
                ("Action", f"{policy['action']} (mute {policy['mute_seconds']}s)"),
            ]
        )
        await reply(message, 
            panel(
                "Anti-spam settings",
                icon=ctx.theme.emoji("shield"),
                subtitle="Enforced by the watcher that ships with this module.",
                table=table,
                note=(
                    "<code>/antispam on|off</code> · <code>limit 7</code> · <code>action mute</code> · "
                    "<code>links off</code> · <code>invites off</code> · <code>keyword word</code> · "
                    "<code>keyword-clear</code>"
                ),
                footer="Staff and approved members are never auto-punished.",
            )
        )

    async def modlog(client, message):
        if not await _guard(client, message):
            return
        try:
            committed = await policy_history(ctx, message.chat.id)
            committed += await rules_history(ctx, message.chat.id)
            committed += await trust_history(ctx, message.chat.id)
            committed += await restriction_history(ctx, message.chat.id)
            committed += await blocklist_history(ctx, message.chat.id)
        except (PolicyError, RulesError, TrustError, CaseError, BlocklistError):
            await reply(message, "Moderation history could not be loaded. Please try again shortly.")
            return
        history = sorted([*ctx.chats.history(message.chat.id, limit=10), *committed], key=lambda row: row.get("at", 0), reverse=True)[:10]
        if not history:
            await reply(message, 
                panel(
                    "Moderation log",
                    icon=ctx.theme.emoji("stats"),
                    lines=["No moderation actions recorded yet."],
                    footer="Actions are appended when they happen.",
                )
            )
            return
        table = Table(
            headers=("Action", "Target", "Reason", "When"),
            rows=tuple(
                (
                    record.get("action", "?").upper(),
                    str(record.get("target") or "-"),
                    record.get("reason") or "no reason",
                    time.strftime("%d %b %H:%M", time.gmtime(record.get("at", 0))),
                )
                for record in history
            ),
            aligns=("left", "right", "left", "left"),
            total_width=56,
        )
        await reply(message, 
            panel(
                "Moderation log",
                icon=ctx.theme.emoji("stats"),
                subtitle="Newest first.",
                table=table,
                footer="Recent actions for this group · times in UTC. Protection changes are read from committed audit history.",
            )
        )

    def report_api_failure(handler):
        @wraps(handler)
        async def guarded(client, message):
            try:
                return await handler(client, message)
            except PartialKickError as exc:
                await reply(message, str(exc))
            except FloodWait as exc:
                await reply(message, f"Telegram rate limit: try again in {int(exc.value)} seconds. The action was not confirmed.")
            except RPCError as exc:
                logger.warning("Moderation action %s failed: %s", handler.__name__, type(exc).__name__)
                await reply(message, f"Telegram could not complete this action ({type(exc).__name__}). Check my administrator rights and the target member. The action was not confirmed.")
        return guarded

    return MANIFEST, {
        **build_antiflood(ctx),
        **build_restrictions(ctx),
        **build_blocklists(ctx),
        "warn": warn,
        "warnings": warnings,
        "warns": warnings,
        "unwarn": unwarn,
        "mute": report_api_failure(mute),
        "unmute": report_api_failure(unmute),
        "kick": report_api_failure(kick),
        "ban": report_api_failure(ban),
        "unban": report_api_failure(unban),
        "purge": purge,
        "note": note,
        "approve": approve, "unapprove": unapprove, "approval": approval, "approved": approved,
        "antispam": antispam,
        "modlog": modlog,
    }
