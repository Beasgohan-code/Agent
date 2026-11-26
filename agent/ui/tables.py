"""Richgram native tables/headings with a box-free compatibility fallback.

Native delivery uses rich_table/rich_heading/rich_note/rich_footer. When the
transport refuses rich formatting, full labels and values remain readable HTML,
without monospace grids or clipped columns. Table.render is a legacy explicit
text utility; message delivery never uses it. Plain cells are escaped while
Markup cells deliberately retain their caller-owned HTML.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

from richgram import rich_footer, rich_heading, rich_hr, rich_note, rich_table

_TAG_RE = re.compile(r"<[^>]+>")
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\ufeff", "\u00ad"}
_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}

#: Box-drawing characters for the default border.
BOX = {
    "tl": "\u250c", "tm": "\u252c", "tr": "\u2510",
    "ml": "\u251c", "mm": "\u253c", "mr": "\u2524",
    "bl": "\u2514", "bm": "\u2534", "br": "\u2518",
    "h": "\u2500", "v": "\u2502",
}

STYLES = ("box", "plain")
ALIGNMENTS = ("left", "right", "center")

#: Whether new panels are rendered as native rich tables. Flipped off for good by
#: :func:`set_rich` when Telegram explicitly reports rich support unavailable.
_RICH = True


def rich_enabled() -> bool:
    return _RICH


def set_rich(enabled: bool) -> None:
    """Choose the rendering used from now on (called by the sender on failure)."""
    global _RICH
    _RICH = bool(enabled)


class Markup(str):
    """A cell value that is already HTML and must not be escaped."""


def markup(value: object) -> Markup:
    """Mark a cell as HTML, e.g. ``markup(f"<code>{escaped}</code>")``."""
    return Markup("" if value is None else str(value))


class Panel(str):
    """A rendered panel that knows how to degrade.

        The string value is the rich form; ``classic`` is the same content as HTML
        Telegram has always accepted. :mod:`agent.utils.rich` picks between them, so
        a deployment without rich messages still gets untruncated label/value rows.
        
    """

    classic: str

    def __new__(cls, rich: str, classic: str) -> "Panel":
        panel = super().__new__(cls, rich)
        panel.classic = classic
        return panel


def plain(text: object) -> str:
    """Cell text with any markup removed, so ``<pre>`` never shows raw tags."""
    value = "" if text is None else str(text)
    return html.unescape(_TAG_RE.sub("", value))


def char_width(char: str) -> int:
    """Columns *char* occupies in a monospace font."""
    if char in _ZERO_WIDTH or char in _VARIATION_SELECTORS or unicodedata.combining(char):
        # U+FE0E/U+FE0F pick a glyph style, they do not take a column of their
        # own. Counting them as one is what shifts every row that carries "⚙️"
        # by a space relative to the rows that do not.
        return 0
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    codepoint = ord(char)
    # Emoji and miscellaneous-symbol blocks render double width in Telegram.
    if 0x1F000 <= codepoint <= 0x1FAFF or 0x2600 <= codepoint <= 0x2BFF:
        return 2
    return 1


def text_width(text: object) -> int:
    """Display width of *text*, ignoring markup."""
    return sum(char_width(char) for char in plain(text))


def clip(text: object, width: int) -> str:
    """Truncate to *width* columns, appending an ellipsis when it does not fit."""
    body = plain(text)
    if width <= 0:
        return ""
    if text_width(body) <= width:
        return body
    if width == 1:
        return "\u2026"
    kept: list[str] = []
    used = 0
    for char in body:
        step = char_width(char)
        if used + step > width - 1:
            break
        kept.append(char)
        used += step
    return "".join(kept) + "\u2026"


def pad(text: object, width: int, align: str = "left") -> str:
    """Pad *text* to exactly *width* columns."""
    body = clip(text, width)
    gap = max(0, width - text_width(body))
    if align == "right":
        return " " * gap + body
    if align == "center":
        left = gap // 2
        return " " * left + body + " " * (gap - left)
    return body + " " * gap


@dataclass(frozen=True)
class Table:
    """Native Richgram table with label/value compatibility rendering."""

    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    aligns: tuple[str, ...] = ()
    style: str = "box"
    max_column: int = 26
    min_column: int = 3
    total_width: int = 44

    def __post_init__(self) -> None:
        # Accept any sequence; normalise to tuples so the dataclass stays hashable.
        if not isinstance(self.headers, tuple):
            object.__setattr__(self, "headers", tuple(self.headers))
        object.__setattr__(
            self, "rows", tuple(tuple(row) for row in self.rows)
        )
        if not isinstance(self.aligns, tuple):
            object.__setattr__(self, "aligns", tuple(self.aligns))

    # -- geometry ----------------------------------------------------------

    @property
    def columns(self) -> int:
        return max(
            [len(self.headers)] + [len(row) for row in self.rows] or [0]
        )

    def _cells(self, row: Sequence[object]) -> list[object]:
        # Objects, not strings: a Markup cell has to keep its type through
        # padding so the native renderer can tell HTML from text.
        cells = ["" if cell is None else cell for cell in row]
        while len(cells) < self.columns:
            cells.append("")
        return cells[: self.columns]

    def widths(self) -> list[int]:
        """Column widths, capped so the whole table fits ``total_width``."""
        if not self.columns:
            return []
        widths = [self.min_column] * self.columns
        for index, header in enumerate(self._cells(self.headers)):
            widths[index] = max(widths[index], text_width(header))
        for row in self.rows:
            for index, cell in enumerate(self._cells(row)):
                widths[index] = max(widths[index], text_width(cell))
        widths = [min(width, self.max_column) for width in widths]

        frame = 3 * len(widths) + 1 if self.style == "box" else 2 * (len(widths) - 1)
        budget = max(self.total_width, self.min_column * len(widths))
        while sum(widths) + frame > budget:
            widest = max(range(len(widths)), key=lambda i: widths[i])
            if widths[widest] <= self.min_column:
                break
            widths[widest] -= 1
        return widths

    def _align_for(self, index: int) -> str:
        if index < len(self.aligns) and self.aligns[index] in ALIGNMENTS:
            return self.aligns[index]
        return "left"

    def _line(self, cells: Sequence[object], widths: Sequence[int]) -> str:
        padded = [
            pad(cell, width, self._align_for(index))
            for index, (cell, width) in enumerate(zip(self._cells(cells), widths))
        ]
        if self.style == "box":
            return BOX["v"] + " " + (" " + BOX["v"] + " ").join(padded) + " " + BOX["v"]
        return "  ".join(padded).rstrip()

    def _rule(self, widths: Sequence[int], left: str, middle: str, right: str) -> str:
        span = (BOX["h"] * (width + 2) for width in widths)
        return left + middle.join(span) + right

    # -- rendering ---------------------------------------------------------

    def render(self) -> str:
        """Plain monospace text, borders included."""
        if not self.columns:
            return ""
        widths = self.widths()
        lines: list[str] = []
        boxed = self.style == "box"
        if boxed:
            lines.append(self._rule(widths, BOX["tl"], BOX["tm"], BOX["tr"]))
        if self.headers:
            lines.append(self._line(self.headers, widths))
            if self.rows:
                if boxed:
                    lines.append(self._rule(widths, BOX["ml"], BOX["mm"], BOX["mr"]))
                else:
                    gap = "  ".join(BOX["h"] * width for width in widths)
                    lines.append(gap)
        for row in self.rows:
            lines.append(self._line(row, widths))
        if boxed:
            lines.append(self._rule(widths, BOX["bl"], BOX["bm"], BOX["br"]))
        return "\n".join(lines)

    def classic_block(self) -> str:
        """Readable untruncated labels when native tables cannot be delivered.

        No box art, column padding or fixed-width clipping in user messages.
        Plain cells are escaped; explicit Markup retains safe HTML semantics.
        """
        if not self.columns:
            return ""
        headers = [self._cell_html(cell) for cell in self._cells(self.headers)] if self.headers else []
        blocks = []
        for row in self.rows:
            cells = [self._cell_html(cell) for cell in self._cells(row)]
            if headers:
                blocks.append("\n".join(
                    f"<b>{label}</b>: {value}" if label else value
                    for label, value in zip(headers, cells)))
            elif len(cells) == 2:
                blocks.append(f"<b>{cells[0]}</b>: {cells[1]}")
            else:
                blocks.append("\n".join(cells))
        return "\n\n".join(blocks) if blocks else " · ".join(headers)

    def _cell_html(self, cell: object) -> str:
        if isinstance(cell, Markup):
            return str(cell)
        return html.escape("" if cell is None else str(cell), quote=False)

    def rich_block(self) -> str:
        """The table as a native rich-message ``<table>``."""
        if not self.columns:
            return ""
        headers = [self._cell_html(cell) for cell in self._cells(self.headers)] if self.headers else None
        rows = [
            tuple(self._cell_html(cell) for cell in self._cells(row))
            for row in self.rows
        ]
        return rich_table(headers, rows, border=1)

    def block(self) -> str:
        """The table in whichever form this deployment can deliver."""
        return self.rich_block() if rich_enabled() else self.classic_block()


def kv_table(pairs: Iterable[tuple[object, object]], **kwargs) -> Table:
    """Two-column label/value table."""
    return Table(rows=tuple((label, value) for label, value in pairs), **kwargs)


def _compose(
    heading: str,
    subtitle: str | None,
    table: Table | None,
    lines: Sequence[str],
    note: str | None,
    footer: str | None,
    *,
    rich: bool,
) -> str:
    parts: list[str] = [rich_heading(heading, 2)]
    if subtitle:
        parts.append(subtitle)
    if table is not None:
        block = table.rich_block() if rich else table.classic_block()
        if block:
            parts.append(block)
    parts.extend(lines)
    if note:
        parts.append(rich_note(note))
    if footer:
        if rich:
            parts.append(rich_hr())
        parts.append(rich_footer(footer))
    body = "\n".join(part for part in parts if part)
    if rich:
        return body
    # Classic path: rich_caption turns the heading/note/footer into the tags
    # Telegram has always accepted, and the label/value rows pass through intact.
    from ..utils.sender import to_safe_html

    return to_safe_html(body)


def panel(
    title: str,
    *,
    icon: str = "",
    subtitle: str | None = None,
    table: Table | None = None,
    lines: Sequence[str] = (),
    note: str | None = None,
    footer: str | None = None,
) -> Panel:
    """Compose a heading, a table and closing lines into one message body.

        Returns a :class:`Panel`: rich by default (a native ``<h2>`` over a native
        ``<table>``) with box-free HTML kept as ``.classic`` for a client that
        cannot send rich messages.
        
    """
    from .theme import panel_icon

    # One shared visual layer reaches all feature studios while preserving their
    # content, explicit icons, footer instructions and callback identities.
    if not icon and title and title[0].isascii() and title[0].isalnum():
        icon = panel_icon(title)
    if footer is None:
        from .identity import controller_label
        footer = controller_label("Meiko · /help · Prefixes / ! . # $ % &amp; ?", "/help · Prefixes / ! . # $ % &amp; ?")
    heading = f"{icon} {title}".strip()
    if rich_enabled():
        return Panel(
            _compose(heading, subtitle, table, lines, note, footer, rich=True),
            _compose(heading, subtitle, table, lines, note, footer, rich=False),
        )
    classic = _compose(heading, subtitle, table, lines, note, footer, rich=False)
    return Panel(classic, classic)
