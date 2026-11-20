"""Additional manual restrictions without changing existing command semantics."""

import html
import re
from datetime import datetime, timedelta, timezone
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.admin_settings import denied
from ...platform.commands import replied_message
from ...platform.restriction_cases import begin, finish, CaseError
from ...utils.rich import reply
from .antiflood import duration

COMMANDS = (
    "tban",
    "tmute",
    "dban",
    "dmute",
    "dkick",
    "sban",
    "smute",
    "skick",
    "kickme",
)


async def target_and_reason(client, message):
    text = getattr(message, "text", "") or ""
    parts = text.split(maxsplit=1)
    body = parts[1] if len(parts) > 1 else ""
    source=await replied_message(client,message)
    replied=getattr(source,"from_user",None)
    if source is not None and (replied is None or getattr(source,"sender_chat",None) is not None):
        raise ValueError("Reply to a personal member message, not an anonymous sender or channel.")
    if replied is not None:
        return replied.id, body
    start = len(text[: text.find(body)].encode("utf-16-le")) // 2 if body else -1
    for entity in getattr(message, "entities", None) or []:
        user = getattr(entity, "user", None)
        if user is not None and getattr(entity, "offset", None) == start:
            remainder = (
                body.encode("utf-16-le")[entity.length * 2 :]
                .decode("utf-16-le")
                .strip()
            )
            return user.id, remainder
    args = body.split(maxsplit=1)
    if not args:
        raise ValueError(
            "Reply to a user or provide a positive user ID, @username or text mention."
        )
    value = args[0]
    if re.fullmatch(r"[1-9][0-9]{0,18}", value):
        uid = int(value)
    elif re.fullmatch(r"@[A-Za-z0-9_]{1,32}", value):
        uid = (await client.get_users(value)).id
    else:
        raise ValueError("Provide a positive user ID or @username, or reply to a user.")
    return uid, args[1] if len(args) > 1 else ""


def build(ctx):
    from . import (
        is_moderator,
        target_is_protected,
        kick_member,
        MUTE_PERMISSIONS,
        PartialKickError,
    )

    async def record_outcome(identity, outcome):
        try:
            await finish(ctx, identity, outcome)
            return ""
        except CaseError:
            return " Audit outcome could not be recorded; check Telegram state before retrying."

    def handler(command):
        async def call(client, message):
            user = getattr(message, "from_user", None)
            chat = getattr(message, "chat", None)
            if (
                getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP)
                or type(getattr(user, "id", None)) is not int
                or user.id <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use restriction commands as yourself inside a group."
                )
                return
            identity = None
            try:
                cleanup = command.startswith(("d", "s"))
                silent = command.startswith("s")
                self_kick = command == "kickme"
                if not self_kick:
                    if not await is_moderator(
                        client, message, need="can_restrict_members"
                    ):
                        await denied(
                            ctx, message, "You need Restrict members permission."
                        )
                        return
                    if cleanup and not await is_moderator(
                        client, message, need="can_delete_messages"
                    ):
                        await denied(
                            ctx,
                            message,
                            "You also need Delete messages permission for this variant.",
                        )
                        return
                replied = await replied_message(client,message)
                replied_chat = getattr(getattr(replied, "chat", None), "id", None)
                if replied_chat is not None and replied_chat != chat.id:
                    raise ValueError(
                        "Reply to a message from this group, not an external chat."
                    )
                if command.startswith("d") and (
                    replied is None or getattr(replied, "from_user", None) is None
                ):
                    raise ValueError(
                        "Delete-action commands must reply to a user message."
                    )
                if self_kick:
                    if len((message.text or "").split()) != 1:
                        raise ValueError("Usage: /kickme")
                    target, reason = user.id, "self-requested kick"
                else:
                    target, reason = await target_and_reason(client, message)
                if type(target) is not int or not 0 < target < 2**63:
                    raise ValueError("Invalid personal target identity.")
                if not self_kick and target == user.id:
                    raise ValueError(
                        "Use /kickme for a self-requested removal; no action attempted."
                    )
                if await target_is_protected(client, chat.id, target):
                    raise ValueError(
                        "Cannot act on an administrator or a user whose membership could not be verified."
                    )
                seconds = 0
                rest = reason.split(maxsplit=1)
                if command in ("tban", "tmute"):
                    if not rest:
                        raise ValueError(
                            "A duration is required, for example 4m, 3h, 6d or 5w."
                        )
                    seconds = duration(rest[0])
                    reason = rest[1] if len(rest) > 1 else ""
                elif (
                    command in ("sban", "smute")
                    and rest
                    and re.fullmatch(r"[0-9]+[smhdw]", rest[0], re.I)
                ):
                    seconds = duration(rest[0])
                    reason = rest[1] if len(rest) > 1 else ""
                if seconds and seconds < 60:
                    raise ValueError(
                        "Timed manual restrictions require at least 60 seconds; shorter values risk Telegram treating them as permanent."
                    )
                if len(reason) > 1000:
                    raise ValueError("Reasons must be at most 1000 characters.")
                me = await client.get_me()
                if target == me.id:
                    raise ValueError("I cannot restrict myself.")
                bot = await client.get_chat_member(chat.id, me.id)
                rights = getattr(bot, "privileges", None)
                if bot.status not in (
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                ) or not getattr(rights, "can_restrict_members", False):
                    raise ValueError("I need Restrict members permission.")
                if cleanup and not getattr(rights, "can_delete_messages", False):
                    raise ValueError(
                        "I also need Delete messages permission for this variant."
                    )
                identity = await begin(
                    ctx, chat.id, message.id, user.id, target, command, seconds, reason
                )
                kwargs = (
                    {
                        "until_date": datetime.now(timezone.utc)
                        + timedelta(seconds=seconds)
                    }
                    if seconds
                    else {}
                )
                if command in ("tban", "dban", "sban"):
                    result = await client.ban_chat_member(chat.id, target, **kwargs)
                    outcome = "banned"
                elif command in ("tmute", "dmute", "smute"):
                    result = await client.restrict_chat_member(
                        chat.id, target, MUTE_PERMISSIONS, **kwargs
                    )
                    outcome = "muted"
                else:
                    await kick_member(
                        client,
                        ctx,
                        chat.id,
                        target,
                        actor_id=user.id,
                        source=command,
                        confirm=True,
                    )
                    result = True
                    outcome = "kicked"
                if result is not True:
                    note = await record_outcome(identity, "unconfirmed")
                    await reply(
                        message,
                        "Telegram did not confirm this restriction. Check current state before retrying."
                        + note,
                    )
                    return
                failures = []
                if cleanup:
                    ids = []
                    if replied is not None:
                        ids.append(getattr(replied, "id", None))
                    if silent:
                        ids.append(message.id)
                    for mid in ids:
                        try:
                            if (
                                type(mid) is not int
                                or mid <= 0
                                or await client.delete_messages(chat.id, mid)
                                is not True
                            ):
                                failures.append("message cleanup unconfirmed")
                        except Exception:
                            failures.append("message cleanup unconfirmed")
                note = await record_outcome(
                    identity, "partial" if failures else "applied"
                )
                if getattr(ctx, "db", None) is None:
                    ctx.chats.log(
                        chat.id,
                        command,
                        actor_id=user.id,
                        target_id=target,
                        reason=reason,
                    )
                if silent and not failures and not note:
                    return
                await reply(
                    message,
                    f"Member <code>{target}</code> {outcome}"
                    + (f" for {seconds}s" if seconds else "")
                    + "."
                    + (" " + html.escape(reason) if reason else "")
                    + (" Message cleanup was not confirmed." if failures else "")
                    + note,
                )
            except PartialKickError as error:
                note = await record_outcome(identity, "partial") if identity else ""
                await reply(message, str(error) + note)
            except (ValueError, CaseError) as error:
                await reply(message, html.escape(str(error)))
            except Exception:
                note = await record_outcome(identity, "unconfirmed") if identity else ""
                await reply(
                    message,
                    "Restriction could not be confirmed. Check current Telegram state before retrying."
                    + note,
                )

        return call

    return {command: handler(command) for command in COMMANDS}
