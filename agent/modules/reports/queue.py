"""The report queue's small pieces: arguments, formatting, and the DM to the owner.

``/appeal`` promises that the owner hears about it, so :func:`notify_owner`
returns the sentence the reply shows — including the honest "could not deliver"
case, which is better than a claim that never left the process.
"""

import html
import logging

from pyrogram.enums import ParseMode

logger = logging.getLogger(__name__)

MAX_REASON = 400


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split(maxsplit=1)


def _reason(message) -> str:
    parts = _args(message)
    return (parts[1].strip() if len(parts) > 1 else "")[:MAX_REASON]


def replicated(entries: list[dict]) -> list[dict]:
    """Newest last, capped for a phone-sized table."""
    return entries[-10:]


async def _notify_owner(client, owner_id, message, number: int, text: str) -> str:
    """DM the owner, and say honestly whether it worked."""
    if owner_id is None:
        return "No owner is configured, so nobody was notified automatically."
    try:
        await client.send_message(
            owner_id,
            f"<b>Appeal #{number}</b> from user "
            f"<code>{getattr(message.from_user, 'id', '?')}</code>\n"
            f"Chat: <code>{getattr(message.chat, 'id', '?')}</code>\n{html.escape(text)}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:  # noqa: BLE001 - reported to the member
        logger.warning("appeal notification unconfirmed (%s)", type(exc).__name__)
        return f"Could not reach the owner ({type(exc).__name__})."
    return "The owner was notified."
