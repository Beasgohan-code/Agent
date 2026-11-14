"""Agent — one way to answer, rich when the deployment allows it.

Telegram Bot API 10.3 can render a real table, a real heading and collapsible
details, but only through a *rich message* (``send_rich_message``). A bot that
has it gets native tables; a deployment whose client library predates it — or
whose Telegram build refuses the call — falls back to the HTML that has always
worked, with tables drawn in ``<pre>``.

The fallback is not per-message guesswork: the first refusal flips
:func:`agent.ui.tables.set_rich` off for the whole process, so the UI stops
producing ``<table>`` at all instead of degrading one message at a time.

Only *sending* is covered here. Telegram has no method to edit a rich message,
so the edited screens (`/menu` navigation) keep the monospace grid — editing is
what makes those screens feel instant, and losing the edit to gain a table would
be a bad trade.
"""

from __future__ import annotations

import logging
import re

from pyrogram.types import InputRichMessage, ReplyParameters

from ..ui import tables

logger = logging.getLogger(__name__)

#: Tags only a rich message can render; seeing one means "send this richly".
_RICH_ONLY = re.compile(
    r"</?(?:h[1-6]|table|thead|tbody|tr|th|td|details|summary|mark|hr|footer"
    r"|tg-button-row|tg-button|tg-math-block|tg-collage|tg-slideshow|tg-map"
    r"|tg-document|tg-thinking|button|img)(?=[\s/>])",
    re.IGNORECASE,
)


def needs_rich(text: str) -> bool:
    """Does *text* use markup only a rich message can render?"""
    return bool(text) and bool(_RICH_ONLY.search(text))


def available(client) -> bool:
    """Can *client* deliver a rich message at all?"""
    return hasattr(client, "send_rich_message")


async def send(client, chat_id, text: str, *, reply_markup=None, **kwargs):
    """Send *text*: rich when possible, plain HTML otherwise."""
    payload = str(text or "")
    if not payload:
        return None
    if tables.rich_enabled() and needs_rich(payload):
        if not available(client):
            _cannot(client)
            payload = _classic_form(text, payload)
        else:
            try:
                return await client.send_rich_message(
                    chat_id=chat_id,
                    rich_text=InputRichMessage(html=payload),
                    reply_markup=reply_markup,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001 - downgrade, never lose it
                _refused(exc)
                payload = _classic_form(text, payload)
    return await client.send_message(
        chat_id=chat_id, text=payload, reply_markup=reply_markup, **kwargs
    )


async def reply(message, text, **kwargs):
    """Reply to *message*: rich when possible, plain HTML otherwise."""
    payload = str(text or "")
    if not payload:
        return None
    client = getattr(message, "_client", None)
    if tables.rich_enabled() and needs_rich(payload):
        if not available(client):
            _cannot(client)
            payload = _classic_form(text, payload)
        else:
            try:
                return await client.send_rich_message(
                    chat_id=message.chat.id,
                    rich_text=InputRichMessage(html=payload),
                    reply_markup=kwargs.pop("reply_markup", None),
                    reply_parameters=ReplyParameters(message_id=message.id),
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001 - downgrade, never lose it
                _refused(exc)
                payload = _classic_form(text, payload)
    return await message.reply(payload, **kwargs)


def _refused(exc: Exception) -> None:
    """Telegram said no: stop producing tables for this process."""
    logger.warning(
        "Telegram refused a rich message (%s: %s); switching the UI to the "
        "classic grid.",
        type(exc).__name__,
        exc,
    )
    tables.set_rich(False)


def _cannot(client) -> None:
    """The client library has no rich support: same downgrade, said once."""
    logger.info(
        "%s has no send_rich_message; using the classic grid.",
        type(client).__name__,
    )
    tables.set_rich(False)


def _classic_form(text, payload: str) -> str:
    """The best classic rendering available for *text*.

    A :class:`agent.ui.tables.Panel` carries its own monospace form, which keeps
    the table aligned; anything else is normalised from its rich markup.
    """
    return getattr(text, "classic", None) or classic(payload)


def classic(text: str) -> str:
    """The same content as HTML Telegram has always accepted."""
    from .sender import to_safe_html

    return to_safe_html(text)
