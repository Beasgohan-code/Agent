"""Shared design reaches feature panels without changing callbacks or content."""

import pytest
from agent.ui import tables
from agent.ui.theme import Theme
from agent.ui.tables import panel, kv_table


@pytest.mark.parametrize(
    "title",
    [
        "Encoder studio",
        "Moderation",
        "Post maker",
        "Music queue",
        "Linkshare",
        "FileStore",
        "Leech transfer",
        "AI Agent",
    ],
)
def test_feature_panels_have_premium_identity_and_help_footer(title, monkeypatch):
    monkeypatch.setenv("USE_PREMIUM_EMOJI", "1")
    tables.set_rich(True)
    result = panel(title, table=kv_table([("State", "Available")]))
    assert "<tg-emoji " in result
    assert "<table" in result and "<pre>" not in result
    assert "Meiko" in result and "/help" in result
    assert title in result


def test_global_emoji_opt_out_and_explicit_panel_choices_are_preserved(monkeypatch):
    monkeypatch.setenv("USE_PREMIUM_EMOJI", "0")
    assert not Theme().custom_emoji_enabled
    result = panel("Music queue", footer="Session-only", icon="♫")
    assert "<tg-emoji" not in result
    assert "Session-only" in result
    assert "Meiko" not in result  # explicit footer stays authoritative
    assert "♫ Music queue" in result


def test_premium_design_retains_safe_classic_fallback(monkeypatch):
    monkeypatch.setenv("USE_PREMIUM_EMOJI", "1")
    tables.set_rich(True)
    result = panel("Media studio", table=kv_table([("Filename", "<unsafe>")]))
    assert "<table" in result
    assert "<table" not in result.classic
    assert "<unsafe>" not in result and "<unsafe>" not in result.classic
    assert "Meiko" in result.classic


def test_home_workspace_catalog_counts_registration_not_group_activation():
    from agent.ui.screens import workspace_rows, welcome_screen

    rows = workspace_rows({"warn", "ban", "encode", "ask"})
    assert len(rows) == 8
    assert dict(rows)["Moderation"] == "2 registered"
    assert dict(rows)["Encoder"] == "1 registered"
    assert dict(rows)["AI Agent"] == "1 registered"
    assert dict(rows)["Music"] == "Not registered"
    screen = welcome_screen(None, Theme(), active={"help", "warn", "encode", "ask"})
    assert "Workspace" in screen.rich_text
    assert "Registration is not group activation" in screen.rich_text
