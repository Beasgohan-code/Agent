"""Group blocklists: plain-text reasons, safe glob matching and explicit modes."""

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.blocklists import operate, find_match, event, BlocklistError
from ...platform.group_trust import trusted_members
from ...platform.admin_settings import denied
from ...utils.rich import reply
from ...ui.tables import panel, Table
from .antiflood import duration

COMMANDS = (
    "addblocklist",
    "rmblocklist",
    "unblocklistall",
    "rmblocklistall",
    "blocklist",
    "blocklistmode",
    "blocklistdelete",
    "setblocklistreason",
    "resetblocklistreason",
)
logger = logging.getLogger(__name__)


def parse_trigger(body):
    body = body.strip()
    if not body:
        raise ValueError("Provide a trigger; quote phrases containing spaces.")
    if body[0] in ('"', "'"):
        quote = body[0]
        chars = []
        i = 1
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body) and body[i + 1] == quote:
                chars.append(quote)
                i += 2
                continue
            if body[i] == quote:
                if i + 1 < len(body) and not body[i + 1].isspace():
                    raise ValueError(
                        "Separate the quoted trigger from its reason with a space."
                    )
                return "".join(chars), body[i + 1 :].strip()
            chars.append(body[i])
            i += 1
        raise ValueError("Close the trigger quote before the reason.")
    parts = body.split(maxsplit=1)
    if parts[0].startswith("("):
        raise ValueError(
            "Bulk trigger syntax is not supported yet; add one trigger at a time."
        )
    return parts[0], parts[1] if len(parts) > 1 else ""


def build(ctx):
    from . import is_moderator

    def handler(command):
        async def call(client, message):
            chat, user = (
                getattr(message, "chat", None),
                getattr(message, "from_user", None),
            )
            if (
                getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or type(getattr(user, "id", None)) is not int
                or user.id <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use blocklist commands as yourself inside a group."
                )
                return
            if not await is_moderator(client, message, need="can_change_info"):
                await denied(
                    ctx,
                    message,
                    "You need Change group info permission to manage blocklists.",
                )
                return
            parts = (getattr(message, "text", "") or "").split(maxsplit=1)
            body = parts[1].strip() if len(parts) > 1 else ""
            try:
                op = None
                value = None
                if command == "addblocklist":
                    value = parse_trigger(body)
                    if re.search(
                        r"\{(?:s?ban|tban|s?mute|tmute|s?kick|s?warn)\b", value[1], re.I
                    ):
                        raise ValueError(
                            "Per-trigger action syntax is not supported yet. Set the group action with /blocklistmode instead."
                        )
                    op = "add"
                elif command == "rmblocklist":
                    value, extra = parse_trigger(body)
                    if extra:
                        raise ValueError(
                            "Quote a multi-word trigger; /rmblocklist takes no reason."
                        )
                    op = "remove"
                elif command in ("unblocklistall", "rmblocklistall"):
                    owner = await client.get_chat_member(chat.id, user.id)
                    if owner.status != ChatMemberStatus.OWNER:
                        raise ValueError(
                            "Only the current chat owner can remove all blocklist triggers."
                        )
                    if not body:
                        await reply(
                            message,
                            f"This removes every blocklist trigger in this group, not its mode/settings. Confirm with <code>/{command} confirm</code>.",
                        )
                        return
                    if body.lower() != "confirm":
                        raise ValueError(
                            f"Use /{command} first, then its confirmation command."
                        )
                    op = "clear"
                elif command == "blocklistmode" and body:
                    args = body.lower().split()
                    if not 1 <= len(args) <= 2 or (args[0] in ("tban", "tmute")) != (
                        len(args) == 2
                    ):
                        raise ValueError(
                            "Usage: /blocklistmode nothing|warn|ban|mute|kick|tban duration|tmute duration"
                        )
                    op = "mode"
                    value = (args[0], duration(args[1]) if len(args) == 2 else 0)
                elif command == "blocklistdelete" and body:
                    if body.lower() not in ("on", "off", "yes", "no", "true", "false"):
                        raise ValueError("Usage: /blocklistdelete yes|no|on|off")
                    op, value = "delete", body.lower() in ("on", "yes", "true")
                elif command == "setblocklistreason":
                    if not body:
                        raise ValueError("Usage: /setblocklistreason reason text")
                    op, value = "reason", body
                elif command == "resetblocklistreason":
                    if body:
                        raise ValueError("Usage: /resetblocklistreason")
                    op, value = "reason", ""
                page = 1
                if command == "blocklist" and body:
                    if (
                        not body.isascii()
                        or not body.isdecimal()
                        or len(body) > 4
                        or int(body) < 1
                    ):
                        raise ValueError("Usage: /blocklist [page]")
                    page = int(body)
                policy = await operate(
                    ctx,
                    chat.id,
                    op,
                    value,
                    actor=user.id if op else None,
                    client=client,
                )
                entries = policy["entries"]
                pages = max(1, (len(entries) + 4) // 5)
                if page > pages:
                    raise ValueError(f"Choose a blocklist page from 1 to {pages}.")
                await reply(
                    message,
                    panel(
                        "Blocklist" + (" updated" if op else ""),
                        subtitle=f"{len(entries)} triggers · {policy['mode']} · {policy['seconds']}s · Delete {'on' if policy['delete'] else 'off'}",
                        table=Table(
                            headers=("Trigger", "Reason preview"),
                            rows=tuple(
                                (e["trigger"][:80], e["reason"][:100] or "default")
                                for e in entries[(page - 1) * 5 : page * 5]
                            ),
                        ),
                        lines=[
                            "Default reason: "
                            + html.escape(
                                (policy["reason"] or "Blocked content.")[:200]
                            )
                        ]
                        if entries
                        else ["No triggers configured."],
                        note="Plain-text reasons. Word-aware, case/accent-insensitive globs: ? one non-space, * non-spaces, ** any text. file: matches entire filenames. Wildcard-only triggers refused. Staff and approved members exempt. Long triggers/reasons shown as previews.",
                        footer=f"Page {page}/{pages} · /blocklist [page]",
                    ),
                )
            except (ValueError, BlocklistError) as error:
                await reply(message, html.escape(str(error)))
            except Exception:
                await reply(
                    message,
                    "Blocklist operation could not be confirmed. Refresh before retrying.",
                )

        return call

    return {command: handler(command) for command in COMMANDS}


async def enforce(ctx, client, message):
    """Return true when this message's blocklist action owns moderation handling."""
    from . import (
        is_moderator,
        target_is_protected,
        kick_member,
        MUTE_PERMISSIONS,
        PartialKickError,
        escalate_warning,
    )
    from . import warn_policy

    chat, user = getattr(message, "chat", None), getattr(message, "from_user", None)
    if (
        getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or user is None
        or getattr(message, "sender_chat", None) is not None
        or getattr(message, "service", None)
    ):
        return False
    claimed = False
    policy = None
    reason = ""
    try:
        policy = await operate(ctx, chat.id)
        if not policy["entries"]:
            return False
        entry = find_match(policy, message)
        if entry is None:
            return False
        if user.id in await trusted_members(ctx, chat.id) or await is_moderator(
            client, message
        ):
            return False
        if await target_is_protected(client, chat.id, user.id):
            return False
        mode = policy["mode"]
        if mode == "nothing" and not policy["delete"]:
            return False
        reason = entry["reason"] or policy["reason"] or "Blocked content."
        claimed = await event(ctx, chat.id, message.id, user.id, mode, reason)
        if not claimed:
            return True
        kwargs = (
            {
                "until_date": datetime.now(timezone.utc)
                + timedelta(seconds=policy["seconds"])
            }
            if mode in ("tban", "tmute")
            else {}
        )
        escalation = ""
        if mode in ("ban", "tban"):
            result = await client.ban_chat_member(chat.id, user.id, **kwargs)
        elif mode in ("mute", "tmute"):
            result = await client.restrict_chat_member(
                chat.id, user.id, MUTE_PERMISSIONS, **kwargs
            )
        elif mode == "kick":
            await kick_member(
                client, ctx, chat.id, user.id, source="blocklist", confirm=True
            )
            result = True
        elif mode == "warn":
            count = ctx.chats.add_warning(
                chat.id, user.id, moderator_id=0, reason=reason
            )
            limit, action = warn_policy(ctx.chats, chat.id)
            if limit and count >= limit:
                escalation = " " + await escalate_warning(
                    client, ctx, message, user.id, action
                )
            result = True
        else:
            result = mode == "nothing"
        if result is not True:
            await event(
                ctx, chat.id, message.id, user.id, mode, reason, outcome="unconfirmed"
            )
            await reply(
                message,
                "Blocklist action was not confirmed. Check current Telegram state before retrying.",
            )
            return True
        partial = False
        if policy["delete"]:
            try:
                partial = await client.delete_messages(chat.id, message.id) is not True
            except Exception:
                partial = True
        await event(
            ctx,
            chat.id,
            message.id,
            user.id,
            mode,
            reason,
            outcome="partial" if partial else "applied",
        )
        if mode != "nothing" or partial:
            await reply(
                message,
                f"Blocklist: {mode} applied to member {user.id}. "
                + html.escape(reason)
                + escalation
                + (" Message deletion was not confirmed." if partial else ""),
            )
        return True
    except PartialKickError as error:
        try:
            await event(
                ctx,
                chat.id,
                message.id,
                user.id,
                policy["mode"],
                reason,
                outcome="partial",
            )
        except BlocklistError:
            pass
        await reply(message, str(error))
        return True
    except Exception:
        if claimed:
            try:
                await event(
                    ctx,
                    chat.id,
                    message.id,
                    user.id,
                    policy["mode"],
                    reason,
                    outcome="unconfirmed",
                )
            except BlocklistError:
                pass
        logger.warning(
            "Blocklist state or action unconfirmed; no automatic retry attempted."
        )
        return claimed
