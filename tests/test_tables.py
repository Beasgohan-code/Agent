"""Monospace tables: geometry, escaping and delivery through richgram."""

import html
import re

from agent.ui.tables import Table, clip, kv_table, panel, plain, text_width
from agent.utils.sender import to_safe_html

PRE_RE = re.compile(r"<pre>([\s\S]*?)</pre>")


def pre_body(markup: str) -> str:
    match = PRE_RE.search(markup)
    assert match is not None, markup
    return html.unescape(match.group(1))


# --- measuring -------------------------------------------------------------


def test_display_width_counts_wide_characters_as_two_columns():
    assert text_width("abc") == 3
    assert text_width("\u65e5\u672c\u8a9e") == 6


def test_display_width_ignores_markup_and_zero_width_joiners():
    assert text_width("<b>bold</b>") == 4
    assert text_width("a\u200db") == 2


def test_clip_keeps_short_text_and_marks_long_text():
    assert clip("abc", 10) == "abc"
    assert clip("abcdef", 4) == "abc\u2026"
    assert clip("anything", 0) == ""


def test_plain_strips_tags_instead_of_leaking_them_into_pre():
    assert plain("<b>bold</b> &amp; <i>italic</i>") == "bold & italic"


# --- rendering -------------------------------------------------------------


def test_box_table_lines_all_have_the_same_display_width():
    table = Table(
        headers=("Slug", "Name", "State"),
        rows=(("ops", "Operations", "on"), ("moderation", "Moderation", "off")),
    )

    lines = table.render().splitlines()

    assert lines[0].startswith("\u250c") and lines[-1].startswith("\u2514")
    assert len({text_width(line) for line in lines}) == 1


def test_a_table_without_headers_has_no_rule_between_header_and_body():
    body = Table(rows=(("a", "b"), ("c", "d"))).render()

    assert "\u251c" not in body


def test_header_only_table_still_renders():
    body = Table(headers=("one", "two")).render()

    assert "one" in body and "two" in body


def test_plain_style_draws_no_borders():
    body = Table(headers=("a", "b"), rows=(("1", "2"),), style="plain").render()

    assert "\u2502" not in body and "\u250c" not in body
    assert "a" in body and "2" in body


def test_cells_are_clipped_to_the_column_width():
    body = Table(headers=("Name",), rows=(("x" * 100,),), max_column=8).render()

    assert "\u2026" in body
    assert max(text_width(line) for line in body.splitlines()) <= 12


def test_numeric_columns_can_be_right_aligned():
    body = Table(headers=("n",), rows=(("1",), ("100",)), aligns=("right",)).render()
    rows = body.splitlines()
    short, long = rows[3], rows[4]

    # Right alignment: both values end in the same column.
    assert short.index("1") > long.index("1")


def test_wide_values_stay_inside_the_total_width_budget():
    table = Table(
        headers=("Label", "Value"),
        rows=(("Label", "v" * 200),),
        max_column=40,
        total_width=30,
    )

    assert max(text_width(line) for line in table.render().splitlines()) <= 30


def test_ragged_rows_are_padded_to_the_column_count():
    body = Table(headers=("a", "b", "c"), rows=(("1",),)).render()

    assert body.count("\u2502") >= 8


def test_block_escapes_ampersands_and_drops_tags_from_cells():
    body = Table(headers=("cmd",), rows=(("/x <tag> & co",),)).block()

    # Telegram does not parse nested tags inside <pre>, so a tag in a cell is
    # removed rather than escaped-and-shown.
    assert "<tag>" not in body
    assert "&amp;" in body


def test_kv_table_has_no_header_row():
    body = kv_table([("State", "online")]).render()

    assert "State" in body and "online" in body


# --- delivery --------------------------------------------------------------


def test_richgram_normalisation_cannot_collapse_pre_whitespace():
    """The regression that made every table look broken in Telegram."""
    markup = "<pre>\u2502 a    \u2502 b \u2502</pre>"

    assert to_safe_html(markup) == markup


def test_panel_keeps_alignment_after_normalisation():
    table = Table(headers=("Slug", "State"), rows=(("ops", "on"), ("group", "off")))

    rendered = panel("Plugins", table=table)

    lines = pre_body(rendered).splitlines()
    assert len({text_width(line) for line in lines}) == 1
    assert "ops" in pre_body(rendered)


def test_panel_normalises_headings_and_notes_but_not_the_table():
    rendered = panel(
        "Plugins",
        table=Table(headers=("a",), rows=(("1",),)),
        note="Toggle with <code>/plugin</code>",
        footer="owner only",
    )

    assert rendered.startswith("<b>")          # <h2> became bold
    assert "<blockquote>" in rendered
    assert "owner only" in rendered
    assert "<pre>" in rendered


def test_panel_without_a_table_has_no_pre_block():
    rendered = panel("Empty", lines=["nothing to show"])

    assert "<pre>" not in rendered
    assert "nothing to show" in rendered


def test_panel_escapes_nothing_it_should_not_and_tags_inside_cells():
    rendered = panel("X", table=Table(headers=("v",), rows=(("<script>",),)))

    body = pre_body(rendered)
    assert "<script>" not in body
