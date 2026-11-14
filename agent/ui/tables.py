"""Agent — monospace tables for Telegram messages.

Standard Telegram HTML has no table element, so a table that actually lines up
has to be monospace text inside ``<pre>``. That is what this module builds: the
caller passes plain cells, the renderer pads them to a shared width and draws
box-drawn borders.

Two consequences are baked in rather than left to chance:

* **Cells are escaped, never formatted.** Telegram does not parse nested tags
  inside ``<pre>``, so a cell that arrives with ``<b>`` in it would be shown
  literally. Tags are stripped and the text re-escaped.
* **Width is display width, not ``len()``.** East-Asian characters and emoji
  occupy two columns in a monospace font; counting them as one is what makes
  hand-written tables drift out of alignment.

Custom emoji are deliberately not used inside tables for the same reason: their
rendered width is the client's choice, so a premium glyph in a cell would break
the grid. Premium glyphs belong in headings, notes and footers, which
:func:`panel` handles.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

from richgram import rich_footer, rich_heading, rich_hr, rich_note

_TAG_RE = re.compile(r"<[^>]+>")
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\ufeff", "\u00ad"}

#: Box-drawing characters for the default border.
BOX = {
    "tl": "\u250c", "tm": "\u252c", "tr": "\u2510",
    "ml": "\u251c", "mm": "\u253c", "mr": "\u2524",
    "bl": "\u2514", "bm": "\u2534", "br": "\u2518",
    "h": "\u2500", "v": "\u2502",
}

STYLES = ("box", "plain")
ALIGNMENTS = ("left", "right", "center")


def plain(text: object) -> str:
    """Cell text with any markup removed, so ``<pre>`` never shows raw tags."""
    value = "" if text is None else str(text)
    return html.unescape(_TAG_RE.sub("", value))


def char_width(char: str) -> int:
    """Columns *char* occupies in a monospace font."""
    if char in _ZERO_WIDTH or unicodedata.combining(char):
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
    """A fixed-width table rendered as ``<pre>`` text."""

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

    def _cells(self, row: Sequence[object]) -> list[str]:
        cells = ["" if cell is None else str(cell) for cell in row]
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

    def block(self) -> str:
        """The table as Telegram-safe ``<pre>`` markup."""
        body = self.render()
        if not body:
            return ""
        return f"<pre>{html.escape(body, quote=False)}</pre>"


def kv_table(pairs: Iterable[tuple[object, object]], **kwargs) -> Table:
    """Two-column label/value table."""
    return Table(rows=tuple((label, value) for label, value in pairs), **kwargs)


def panel(
    title: str,
    *,
    icon: str = "",
    subtitle: str | None = None,
    table: Table | None = None,
    lines: Sequence[str] = (),
    note: str | None = None,
    footer: str | None = None,
) -> str:
    """Compose a title, table and closing lines into standard Telegram HTML.

    The result is ready for ``message.reply``: the rich-only blocks (headings,
    rules, footers) are normalised into tags Telegram accepts while the ``<pre>``
    table is passed through with its whitespace intact.
    """
    # Imported lazily: agent.utils.sender pulls in the screen layer, which in
    # turn uses Table for its key/value panels.
    from ..utils.sender import to_safe_html

    parts: list[str] = [rich_heading(f"{icon} {title}".strip(), 2)]
    if subtitle:
        parts.append(subtitle)
    if table is not None:
        block = table.block()
        if block:
            parts.append(block)
    parts.extend(lines)
    if note:
        parts.append(rich_note(note))
    if footer:
        parts.append(rich_hr())
        parts.append(rich_footer(footer))
    return to_safe_html("\n".join(part for part in parts if part))
