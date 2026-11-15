"""Original archive-range link workflow. No reference code or opaque payloads."""

import re
import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...utils.rich import reply
from ...ui.tables import panel, kv_table

logger = logging.getLogger(__name__)
from ...platform.archive_links import create, database, revoke


def private(message):
    uid = getattr(getattr(message, "from_user", None), "id", None)
    chat = getattr(message, "chat", None)
    return (
        type(uid) is int
        and uid > 0
        and getattr(chat, "type", None) == ChatType.PRIVATE
        and chat.id == uid
        and getattr(message, "sender_chat", None) is None
    )


def selection(args):
    """No channel IDs, URLs or expressions: only bounded positive message IDs."""
    explicit = bool(args and args[0].lower() == "ids")
    values = args[1:] if explicit else args
    if not (1 <= len(values) <= 50 if explicit else len(values) == 2) or any(
        not re.fullmatch(r"[1-9][0-9]{0,9}", value) for value in values
    ):
        raise ValueError(
            "Usage: /custom_batch first last or /custom_batch ids id1 id2 … (1–50 unique messages). Optional: --hours=1..168 --uses=1..10000. You can also reply to a forwarded archive message."
        )
    ids = list(map(int, values))
    if any(mid >= 2**31 for mid in ids):
        raise ValueError("Archive message IDs are too large.")
    if explicit:
        if len(set(ids)) != len(ids):
            raise ValueError("Do not repeat message IDs in a custom batch.")
        return ids
    first, last = ids
    if not 0 <= last - first < 50:
        raise ValueError("Choose an ascending range of 1–50 messages.")
    return list(range(first, last + 1))


def archive_reference(value, channel):
    """Resolve private channel URLs only against the configured archive."""
    match = re.fullmatch(r"https://t\.me/c/([1-9][0-9]{0,15})/([1-9][0-9]{0,9})", value)
    if not match or int("-100" + match[1]) != channel:
        raise ValueError(
            "Use a private Telegram message link from this bot’s configured archive channel."
        )
    return match[2]


def link_options(args):
    values, options = [], {}
    for arg in args:
        if arg.startswith("--"):
            match = re.fullmatch(r"--(hours|uses)=([1-9][0-9]{0,4})", arg)
            if not match or match[1] in options:
                raise ValueError("Use --hours=1..168 and --uses=1..10000 once each.")
            options[match[1]] = int(match[2])
        else:
            values.append(arg)
    hours, uses = options.get("hours", 24), options.get("uses")
    if not 1 <= hours <= 168 or (uses is not None and not 1 <= uses <= 10000):
        raise ValueError("Expiry must be 1–168 hours; use limit must be 1–10000.")
    return values, hours, uses


def message_selection(message, channel):
    args = (getattr(message, "text", "") or "").split()[1:]
    args, _, _ = link_options(args)
    if not args:
        forwarded = getattr(message, "reply_to_message", None)
        source = getattr(forwarded, "forward_from_chat", None)
        mid = getattr(forwarded, "forward_from_message_id", None)
        if (
            getattr(source, "id", None) != channel
            or type(mid) is not int
            or not 0 < mid < 2**31
        ):
            raise ValueError(
                "Reply to a forwarded message from the configured archive, or use /custom_batch first last or /custom_batch ids id1 id2 … ."
            )
        return [mid], True
    explicit = args[0].lower() == "ids"
    values = args[1:] if explicit else args
    values = [
        archive_reference(value, channel) if value.startswith("https://") else value
        for value in values
    ]
    return selection((["ids"] if explicit else []) + values), explicit


def build(ctx):
    async def generate(client, message):
        if not private(message) or message.from_user.id != ctx.settings.owner_id:
            await reply(
                message,
                "Only this bot’s configured Owner can create archive links, in private chat.",
            )
            return
        args = (getattr(message, "text", "") or "").split()[1:]
        if len(args) == 2 and args[0].lower() == "revoke":
            try:
                changed = await revoke(ctx, message.from_user.id, args[1])
            except ValueError as error:
                await reply(message, str(error))
                return
            except Exception:
                await reply(
                    message,
                    "Archive revocation was not confirmed. Refresh before retrying.",
                )
                return
            await reply(
                message,
                "Archive link revoked."
                if changed
                else "Archive link was already revoked.",
            )
            return
        channel = getattr(ctx.settings, "storage_channel", None)
        try:
            _, hours, max_uses = link_options(args)
            ids, explicit = message_selection(message, channel)
            database(ctx)
            if type(channel) is not int or not -(2**63) < channel < 0:
                raise ValueError(
                    "Configure this bot’s STORAGE_CHANNEL before creating archive links."
                )
            chat = await client.get_chat(channel)
            if getattr(chat, "type", None) != ChatType.CHANNEL or getattr(
                chat, "has_protected_content", False
            ):
                raise ValueError(
                    "The archive must be a readable channel without protected content."
                )
            me = await client.get_me()
            for uid in (message.from_user.id, me.id):
                member = await client.get_chat_member(channel, uid)
                if member.status not in (
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                ):
                    raise ValueError(
                        "Both the Owner and this bot must be current archive-channel administrators."
                    )
            source = await client.get_messages(channel, ids)
            if (
                not isinstance(source, list)
                or len(source) != len(ids)
                or any(
                    getattr(m, "id", None) != ids[i]
                    or getattr(m, "empty", False)
                    or getattr(m, "service", None)
                    or getattr(m, "has_protected_content", False)
                    for i, m in enumerate(source)
                )
            ):
                raise ValueError(
                    "The range contains missing, protected or service messages. No link was created."
                )
            username = getattr(me, "username", None)
            if not username or not re.fullmatch(r"[A-Za-z0-9_]+", username):
                raise ValueError("This bot has no usable username for a start link.")
            token = await create(
                ctx,
                message.from_user.id,
                channel,
                ids[0],
                ids[-1],
                hours=hours,
                max_uses=max_uses,
                **({"message_ids": ids} if explicit else {}),
            )
        except ValueError as error:
            await reply(message, str(error))
            return
        except Exception:
            logger.warning("Archive link creation unconfirmed; no automatic retry.")
            await reply(
                message,
                "Archive link creation could not be confirmed. No automatic retry attempted.",
            )
            return
        await reply(
            message,
            panel(
                "FileStore archive link",
                table=kv_table(
                    [
                        ("Messages", str(len(ids))),
                        ("Expiry", f"{hours} hours"),
                        (
                            "Request limit",
                            str(max_uses)
                            if max_uses is not None
                            else "Unlimited until expiry",
                        ),
                    ]
                ),
                lines=[
                    f"<code>https://t.me/{username}?start=archive_{token}</code>",
                    "Revoke this link:",
                    f"<code>/custom_batch revoke {token}</code>",
                ],
                note="Anyone with this bearer link can request copies in private chat until expiry. Each admitted delivery request consumes one use, including interrupted deliveries. No file downloads or parent-bot credentials are used. Protected content will not be bypassed. Revoke with /custom_batch revoke token (the part after archive_). Revocation stops new copies; an already in-flight Telegram request may still complete.",
            ),
        )

    async def redeem(client, message, token):
        if not private(message):
            await reply(
                message, "Open archive links in your private chat with this bot."
            )
            return
        delivered = 0
        claimed = False
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]{32}", token):
                raise ValueError("Archive link is invalid or expired.")
            if type(getattr(message, "id", None)) is not int or message.id <= 0:
                raise ValueError("A valid private command message is required.")
            db = database(ctx)
            async with db._pool.acquire(timeout=5) as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT * FROM agent_archive_links WHERE tenant=$1 AND token=$2 AND expires_at>now() AND NOT revoked FOR UPDATE",
                        db.scope,
                        token,
                        timeout=5,
                    )
                    if row is None:
                        raise ValueError("Archive link is invalid or expired.")
                    if row["max_uses"] is not None and row["uses"] >= row["max_uses"]:
                        raise ValueError("Archive request limit reached.")
                    claimed = bool(
                        await conn.fetchval(
                            """INSERT INTO agent_archive_deliveries(tenant,token,user_id,message_id) VALUES($1,$2,$3,$4)
                        ON CONFLICT DO NOTHING RETURNING true""",
                            db.scope,
                            token,
                            message.from_user.id,
                            message.id,
                            timeout=5,
                        )
                    )
                    if claimed:
                        await conn.execute(
                            "UPDATE agent_archive_links SET uses=uses+1 WHERE tenant=$1 AND token=$2",
                            db.scope,
                            token,
                            timeout=5,
                        )
            if not claimed:
                raise ValueError(
                    "This delivery request was already recorded. It will not be automatically replayed."
                )
            chat = await client.get_chat(row["channel_id"])
            if getattr(chat, "type", None) != ChatType.CHANNEL or getattr(
                chat, "has_protected_content", False
            ):
                raise ValueError("Archive access or copying is no longer available.")
            me = await client.get_me()
            for uid in (row["owner_id"], me.id):
                member = await client.get_chat_member(row["channel_id"], uid)
                if member.status not in (
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                ):
                    raise ValueError("Archive administrator access is no longer valid.")
            for mid in row["message_ids"] or range(row["first_id"], row["last_id"] + 1):
                async with db._pool.acquire(timeout=5) as conn:
                    valid = await conn.fetchval(
                        "SELECT 1 FROM agent_archive_links WHERE tenant=$1 AND token=$2 AND expires_at>now() AND NOT revoked",
                        db.scope,
                        token,
                        timeout=5,
                    )
                if not valid:
                    raise ValueError(
                        "Archive link expired or was revoked during delivery."
                    )
                async with db._pool.acquire(timeout=5) as conn:
                    await conn.execute(
                        "INSERT INTO agent_archive_delivery_items(tenant,token,user_id,message_id,source_id) VALUES($1,$2,$3,$4,$5)",
                        db.scope,
                        token,
                        message.from_user.id,
                        message.id,
                        mid,
                        timeout=5,
                    )
                try:
                    sent = await client.copy_message(
                        message.chat.id, row["channel_id"], mid
                    )
                    if type(getattr(sent, "id", None)) is not int or sent.id <= 0:
                        raise ValueError("Telegram did not confirm the next copy.")
                except Exception:
                    async with db._pool.acquire(timeout=5) as conn:
                        await conn.execute(
                            "UPDATE agent_archive_delivery_items SET outcome='unconfirmed' WHERE tenant=$1 AND token=$2 AND user_id=$3 AND message_id=$4 AND source_id=$5",
                            db.scope,
                            token,
                            message.from_user.id,
                            message.id,
                            mid,
                            timeout=5,
                        )
                    raise
                delivered += 1
                async with db._pool.acquire(timeout=5) as conn:
                    async with conn.transaction():
                        await conn.execute(
                            "UPDATE agent_archive_delivery_items SET outcome='applied',destination_id=$6 WHERE tenant=$1 AND token=$2 AND user_id=$3 AND message_id=$4 AND source_id=$5",
                            db.scope,
                            token,
                            message.from_user.id,
                            message.id,
                            mid,
                            sent.id,
                            timeout=5,
                        )
                        await conn.execute(
                            "UPDATE agent_archive_deliveries SET delivered=$5 WHERE tenant=$1 AND token=$2 AND user_id=$3 AND message_id=$4",
                            db.scope,
                            token,
                            message.from_user.id,
                            message.id,
                            delivered,
                            timeout=5,
                        )
            outcome = "applied"
        except Exception:
            outcome = "unconfirmed"
            if not claimed:
                await reply(
                    message,
                    "Archive link unavailable, expired, request limit reached, or this request was already recorded. No new copies attempted.",
                )
                return
        try:
            async with database(ctx)._pool.acquire(timeout=5) as conn:
                await conn.execute(
                    "UPDATE agent_archive_deliveries SET outcome=$5,delivered=$6 WHERE tenant=$1 AND token=$2 AND user_id=$3 AND message_id=$4",
                    database(ctx).scope,
                    token,
                    message.from_user.id,
                    message.id,
                    outcome,
                    delivered,
                    timeout=5,
                )
        except Exception:
            await reply(
                message,
                f"{delivered} copies confirmed by Telegram; saving the delivery outcome was unconfirmed. No automatic retry.",
            )
            return
        if outcome != "applied":
            await reply(
                message,
                f"{delivered} copies confirmed; remaining delivery unconfirmed. Check received messages before trying a new request. No automatic retry.",
            )

    router = getattr(ctx, "deeplinks", None)
    if router is not None:
        router.register("archive", redeem)
    return {"custom_batch": generate}
