"""Agent — one way to answer, rich when the deployment allows it.

Telegram Bot API 10.3 can render a real table, a real heading and collapsible
details, but only through a *rich message* (``send_rich_message``). A bot that
has it gets native tables; a deployment whose client library predates it — or
whose Telegram build refuses the call — falls back to the HTML that has always
worked, with untruncated label/value rows.

Explicit unsupported-feature errors disable rich rendering for the process.
An invalid individual rich card falls back locally; transport, permission and
rate-limit failures propagate without risking a duplicate send.

Editing is covered too: the Bot API edits a rich message through
``edit_message_text(rich_text=…)``, so navigating `/menu` keeps the native table
instead of collapsing the screen into a grid on the first button press. When
either call is refused the classic form is built from the same object — tables
shown as label/value rows without box art.
"""

from __future__ import annotations

import html
import logging
import re

from pyrogram.types import InputRichMessage, ReplyParameters

from ..ui import tables

logger = logging.getLogger(__name__)

#: Any markup tag, for taking the visible text out of an HTML cell.
_CELL_TAG = re.compile(r"<[^>]+>")

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
    return callable(getattr(client, "send_rich_message", None))


async def _send(client, chat_id, text: str, *, reply_markup=None, **kwargs):
    """Send *text*: rich when possible, plain HTML otherwise."""
    payload = str(text or "")
    if not payload:
        return None
    if not tables.rich_enabled() and needs_rich(payload):
        payload = _classic_form(text, payload)
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
            except Exception as exc:  # noqa: BLE001 - classify explicit format rejections
                if not _refused(exc):
                    raise
                payload = _classic_form(text, payload)
    return await client.send_message(
        chat_id=chat_id, text=payload, reply_markup=reply_markup, **kwargs
    )


async def _reply(message, text, **kwargs):
    """Reply to *message*: rich when possible, plain HTML otherwise."""
    payload = str(text or "")
    if not payload:
        return None
    client = getattr(message, "_client", None)
    if not tables.rich_enabled() and needs_rich(payload):
        payload = _classic_form(text, payload)
    if tables.rich_enabled() and needs_rich(payload):
        if not available(client):
            _cannot(client)
            payload = _classic_form(text, payload)
        else:
            try:
                rich_kwargs = dict(kwargs)
                rich_kwargs.setdefault("reply_parameters", ReplyParameters(message_id=message.id))
                return await client.send_rich_message(
                    chat_id=message.chat.id,
                    rich_text=InputRichMessage(html=payload),
                    **rich_kwargs,
                )
            except Exception as exc:  # noqa: BLE001 - classify explicit format rejections
                if not _refused(exc):
                    raise
                payload = _classic_form(text, payload)
    return await message.reply(payload, **kwargs)


def _editor(target):
    """The callable that edits *target*'s message, or ``None``.

    A real :class:`pyrogram.types.CallbackQuery` edits itself; the panel code in
    the plugins also carries the editor on ``query.message``, so both are tried.
    """
    direct = getattr(target, "edit_message_text", None)
    if callable(direct):
        return direct
    message = getattr(target, "message", None)
    nested = getattr(message, "edit_text", None)
    return nested if callable(nested) else None


async def _edit(target, text, *, reply_markup=None):
    """Edit the message *target* (a callback query) points at.

    Rich when the text needs it and the client can send it, classic otherwise;
    the classic form is derived from the same object, so a refused rich edit
    degrades to readable labels rather than to nothing.
    """
    payload = str(text or "")
    if not payload:
        return None
    editor = _editor(target)
    if editor is None:
        return None
    client = getattr(target, "_client", None) or getattr(
        getattr(target, "message", None), "_client", None
    )
    if tables.rich_enabled() and needs_rich(payload) and available(client):
        try:
            return await editor(
                rich_text=InputRichMessage(html=payload), reply_markup=reply_markup
            )
        except Exception as exc:  # noqa: BLE001 - classify before fallback
            if not _refused(exc):
                raise
    return await editor(
        text=_classic_form(text, payload), parse_mode="html", reply_markup=reply_markup
    )


def _refused(exc: Exception) -> bool:
    """Downgrade only explicit rich-format rejections, not transport failures.

    Retrying an ambiguous timeout as plain text could duplicate an already sent
    message. Rate limits and permission errors also belong to the normal caller
    error path, not a process-wide loss of native UI support.
    """
    reason = str(exc).upper()
    unsupported = any(code in reason for code in (
        "RICH_MESSAGE_UNSUPPORTED", "RICH_MESSAGES_UNSUPPORTED",
        "RICH_TEXT_UNSUPPORTED",
    ))
    invalid = any(code in reason for code in (
        "RICH_TEXT_INVALID", "RICH_MESSAGE_INVALID",
    ))
    if not (unsupported or invalid):
        return False
    logger.warning("Telegram rejected rich formatting (%s); using classic HTML.",
                   type(exc).__name__)
    # A malformed individual card must not downgrade every other plugin.
    if unsupported:
        tables.set_rich(False)
    return True


def _cannot(client) -> None:
    """The client library has no rich support: same downgrade, said once."""
    logger.info(
        "%s has no send_rich_message; using box-free HTML.",
        type(client).__name__,
    )
    tables.set_rich(False)


def _classic_form(text, payload: str) -> str:
    """The best classic rendering available for *text*.

        A :class:`agent.ui.tables.Panel` carries its own box-free HTML form;
        anything else is normalised from its rich markup.
        
    """
    return getattr(text, "classic", None) or classic(payload)


#: A native ``<table>``, as emitted by :meth:`agent.ui.tables.Table.rich_block`.
_TABLE_RE = re.compile(r"<table[^>]*>([\s\S]*?)</table>", re.IGNORECASE)
_ROW_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
_CELL_RE = re.compile(r"<t([hd])[^>]*>([\s\S]*?)</t\1>", re.IGNORECASE)


def _cell_text(cell: str) -> str:
    """Visible text of one cell: tags gone, whitespace collapsed."""
    return " ".join(html.unescape(_CELL_TAG.sub("", cell)).split())


def _table_to_classic(match: re.Match) -> str:
    """Convert one native table to readable label/value HTML."""
    headers: tuple[str, ...] = ()
    rows: list[tuple[str, ...]] = []
    for row in _ROW_RE.finditer(match.group(1)):
        cells = [(kind.lower(), _cell_text(text)) for kind, text in _CELL_RE.findall(row.group(1))]
        if not cells:
            continue
        if not headers and not rows and all(kind == "h" for kind, _ in cells):
            headers = tuple(text for _, text in cells)
        else:
            rows.append(tuple(text for _, text in cells))
    if not headers and not rows:
        return ""
    table = tables.Table(
        headers=headers, rows=tuple(rows), max_column=40, total_width=62
    )
    return table.classic_block()


def classic(text: str) -> str:
    """The same content as HTML Telegram has always accepted.

    A native table would arrive as one run-on line — Telegram does not lay out
    ``<table>`` outside a rich message — so it is converted to label/value HTML first.
    """
    from .sender import to_safe_html

    body = text or ""
    if "<table" in body.lower():
        body = _TABLE_RE.sub(_table_to_classic, body)
    body = re.sub(r"<hr\b[^>]*>", "\n", body, flags=re.IGNORECASE)
    return to_safe_html(body)


async def _retry_emoji(operation, text, keyboard):
    """Retry explicit decorative rejections once, never ambiguous delivery failures."""
    from .sender import _emoji_rejected, _has_emoji, _plain_screen
    from ..ui.screens import Screen
    screen = Screen(text, keyboard)
    try:
        return await operation(text, keyboard)
    except Exception as exc:
        if not _has_emoji(screen) or not _emoji_rejected(exc):
            raise
        plain = _plain_screen(screen)
        return await operation(plain.rich_text, plain.keyboard)


async def send(client, chat_id, text: str, *, reply_markup=None, **kwargs):
    async def deliver(body, keyboard):
        return await _send(client, chat_id, body, reply_markup=keyboard, **kwargs)
    return await _retry_emoji(deliver, text, reply_markup)


async def reply(message, text, **kwargs):
    async def deliver(body, keyboard):
        options = dict(kwargs)
        if keyboard is not None or 'reply_markup' in options:
            options['reply_markup'] = keyboard
        return await _reply(message, body, **options)
    return await _retry_emoji(deliver, text, kwargs.get('reply_markup'))


async def edit(target, text, *, reply_markup=None):
    async def deliver(body, keyboard):
        return await _edit(target, body, reply_markup=keyboard)
    return await _retry_emoji(deliver, text, reply_markup)
