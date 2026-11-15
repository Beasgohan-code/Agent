"""Live forum topic management; no owner bypass and no irreversible deletion."""

import logging
from pyrogram.enums import ChatType, ChatMemberStatus
from ...platform.admin_settings import denied
from ...platform.action_topics import operate as action_topic
from ...ui.tables import panel, kv_table
from ...utils.rich import reply

COMMANDS = (
    "newtopic",
    "renametopic",
    "closetopic",
    "reopentopic",
    "actiontopic",
    "setactiontopic",
)
logger = logging.getLogger(__name__)


def allowed(member):
    return getattr(member, "status", None) == ChatMemberStatus.OWNER or (
        getattr(member, "status", None) == ChatMemberStatus.ADMINISTRATOR
        and getattr(getattr(member, "privileges", None), "can_manage_topics", False)
    )


def build(ctx):
    def handler(command):
        async def call(client, message):
            chat = getattr(message, "chat", None)
            actor = getattr(getattr(message, "from_user", None), "id", None)
            if (
                getattr(chat, "type", None) != ChatType.SUPERGROUP
                or type(actor) is not int
                or actor <= 0
                or getattr(message, "sender_chat", None) is not None
            ):
                await reply(
                    message, "Use topic commands as yourself inside a forum supergroup."
                )
                return
            try:
                if not allowed(await client.get_chat_member(chat.id, actor)):
                    await denied(
                        ctx, message, "You need Manage topics permission to do that."
                    )
                    return
                live = await client.get_chat(chat.id)
                if getattr(live, "is_forum", False) is not True:
                    await reply(message, "This group is not a Telegram forum.")
                    return
                me = await client.get_me()
                if not allowed(await client.get_chat_member(chat.id, me.id)):
                    await reply(
                        message, "I need Manage topics permission. No change attempted."
                    )
                    return
                parts = (getattr(message, "text", "") or "").split(maxsplit=1)
                title = parts[1].strip() if len(parts) > 1 else ""
                if command in ("actiontopic", "setactiontopic"):
                    if title:
                        await reply(
                            message,
                            f"Use /{command} without arguments inside the desired topic.",
                        )
                        return
                    destination = None
                    if command == "setactiontopic":
                        destination = getattr(message, "message_thread_id", None)
                        if type(destination) is not int or not 0 < destination < 2**31:
                            await reply(
                                message,
                                "This thread could not be identified. No destination changed.",
                            )
                            return
                    saved = await action_topic(
                        ctx,
                        chat.id,
                        destination,
                        actor=actor if destination is not None else None,
                    )
                    await reply(
                        message,
                        panel(
                            "Action topic",
                            table=kv_table(
                                [
                                    (
                                        "Topic ID",
                                        str(saved)
                                        if saved is not None
                                        else "General (default)",
                                    ),
                                ]
                            ),
                            note="Welcome and goodbye messages use this destination. Run /setactiontopic in General to return there. Delivery failures do not fall back into another topic.",
                        ),
                    )
                    return
                if command in ("newtopic", "renametopic"):
                    if (
                        not 1 <= len(title) <= 128
                        or len(title.encode("utf-16-le")) // 2 > 128
                        or any(ord(c) < 32 for c in title)
                    ):
                        await reply(
                            message,
                            f"Usage: /{command} name — 1–128 UTF-16 units, no control characters.",
                        )
                        return
                elif title:
                    await reply(
                        message, f"Use /{command} without arguments inside the topic."
                    )
                    return
                topic = getattr(message, "message_thread_id", None)
                if command != "newtopic" and (
                    type(topic) is not int or not 0 < topic < 2**31
                ):
                    await reply(
                        message,
                        "Run this command inside the desired topic. Its thread could not be identified; no change attempted.",
                    )
                    return
                if command == "newtopic":
                    result = await client.create_forum_topic(chat.id, title=title)
                    topic = getattr(result, "id", None)
                    confirmed = type(topic) is int and topic > 0
                elif topic == 1:
                    if command == "renametopic":
                        confirmed = (
                            await client.edit_general_forum_topic(chat.id, title=title)
                            is True
                        )
                    elif command == "closetopic":
                        confirmed = (
                            await client.close_general_forum_topic(chat.id) is True
                        )
                    else:
                        confirmed = (
                            await client.reopen_general_forum_topic(chat.id) is True
                        )
                elif command == "renametopic":
                    confirmed = (
                        await client.edit_forum_topic(chat.id, topic, title=title)
                        is True
                    )
                elif command == "closetopic":
                    confirmed = await client.close_forum_topic(chat.id, topic) is True
                else:
                    confirmed = await client.reopen_forum_topic(chat.id, topic) is True
                if not confirmed:
                    await reply(
                        message,
                        "Topic change was not confirmed. Check the current topic before retrying; no automatic retry was attempted.",
                    )
                    return
            except Exception:
                logger.warning(
                    "Topic operation unconfirmed; no automatic retry attempted."
                )
                await reply(
                    message,
                    "Topic permissions or change could not be confirmed. Check the current Telegram topic before retrying.",
                )
                return
            # Notification failure must not be mistaken for failure of the Telegram mutation.
            await reply(
                message,
                panel(
                    "Topic change confirmed",
                    table=kv_table(
                        [
                            ("Action", command),
                            ("Topic ID", str(topic)),
                            *((("Name", title),) if title else ()),
                        ]
                    ),
                    note="Forum settings remain shared across topics. Welcome/goodbye routing is configured with /setactiontopic. Topic deletion is not implemented yet.",
                ),
            )

        return call

    return {command: handler(command) for command in COMMANDS}
