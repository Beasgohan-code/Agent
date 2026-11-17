"""Agent — screen builders.

Two rules keep the screens readable on a phone: prose stays in lists and
quotes, and anything with more than one column of data is a table. Command
references stay prose — a table would truncate the sentence that explains the
command, which is the whole point of ``/help``.
"""

from __future__ import annotations

import re
import difflib
from dataclasses import dataclass
from typing import Callable

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup
from richgram import (
    rich_esc,
    rich_footer,
    rich_heading,
    rich_hr,
    rich_list,
    rich_note,
)

from .. import __version__
from . import keyboards
from .tables import Table, kv_table, markup
from .theme import Theme


def format_uptime(seconds: float) -> str:
    """Human-readable uptime, e.g. ``2d 4h 11m``."""
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass(frozen=True)
class Screen:
    """A rendered screen: rich markup plus the keyboard shown under it."""

    rich_text: str
    keyboard: InlineKeyboardMarkup | None = None


def display_name(user) -> str:
    """Best-effort human name for a Telegram user."""
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    return " ".join(part for part in (first, last) if part)


def _username(user) -> str:
    username = (getattr(user, "username", None) or "").strip()
    return f"@{rich_esc(username)}" if username else "not set"


WORKSPACE_FEATURES = (
    ("encoder", "Encoder"), ("moderation", "Moderation"),
    ("postmaker", "Post maker"), ("music", "Music"),
    ("linkshare", "Linkshare"), ("filestore", "FileStore"),
    ("leech", "Leech"), ("ai_agent", "AI Agent"),
)


def workspace_rows(active):
    """Show registration evidence only, never infer group approval or health."""
    from ..modules import MODULES
    manifests = {module.MANIFEST.slug: module.MANIFEST for module in MODULES}
    rows = []
    active = set(active) if active is not None else None
    for slug, label in WORKSPACE_FEATURES:
        manifest = manifests.get(slug)
        count = len(set(manifest.commands) & active) if active is not None and manifest else 0
        state = (f"{count} registered" if count else "Not registered") if active is not None else "Browse Help"
        rows.append((label, state))
    return rows


def welcome_screen(user, theme: Theme, *, active: set[str] | None = None, bot_username: str | None = None) -> Screen:
    """Compact welcome card for native rich heroes and classic photo captions.

    Tool suggestions come from the live registry. Avoid unverifiable online or
    blanket privacy claims; show policy and available navigation instead.
    """
    if theme.worker_plugins is not None:
        from .workers import overview
        return overview(user, theme, active=active)
    name = display_name(user)
    greeting = (
        f"{theme.emoji('wave')} Hello, <b>{rich_esc(name)}</b>!"
        if name
        else f"{theme.emoji('wave')} Hello!"
    )

    rows = [("Version", __version__), ("Core", "Moderation · always available")]
    if active is not None:
        rows.append(("Commands", str(len(active))))
    suggestions = [
        ("help", "Browse your command library"),
        ("plugins", "Open plugin controls for this chat"),
        ("links", "Manage your existing share links"),
        ("play", "Start a voice-chat music session"),
    ]
    quick = [f"<code>/{command}</code> — {label}" for command, label in suggestions
             if active is None or command in active]
    text = (
        rich_heading(f"{theme.emoji('diamond')} Meiko", 2)
        + "\n<b>Your group. Your workspace.</b>\n"
        + greeting + "\n"
        + rich_note(f"{theme.emoji('shield')} Keep your community protected. "
                    "Bring music, media and useful tools into one focused workspace.")
        + "\n" + kv_table(rows).block()
        + "\n<b>Workspace</b>\n"
        + Table(headers=("Feature", "Commands"), rows=tuple(workspace_rows(active))).block()
        + "\n<b>Try your next action</b>\n"
        + rich_list(quick or ["Open Help below to explore this workspace."])
        + "\n" + rich_hr()
        + rich_footer("Prefixes: / ! . # $ % &amp; ? · Registration is not group activation. Optional plugins need Owner approval and group-admin activation.")
    )
    return Screen(text, keyboards.start_keyboard(bot_username, theme=theme))


#: Command reference sections. Names come from the live registry, descriptions
#: from the same table the Telegram command menu uses, so ``/help`` and the menu
#: can never drift apart.
#: Registered outside the module registry, so the help filter must let them through.
BUILTIN = frozenset({"start", "help", "ping"})

HELP_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("sparkles", "AI Agent", ("ask", "autochat")),
    (
        "bolt",
        "Essentials",
        ("start", "help", "menu", "about", "status", "alive", "uptime", "ping", "cancel", "jobs", "owner",
         "id", "info", "myinfo", "userinfo", "time", "repo", "gu", "tiktok", "x", "yt", "ig"),
    ),
    (
        "gear",
        "Encoding & files",
        (
            "encode", "compress", "sample", "toaudio", "screens",
            "mediainfo", "autorename", "rename", "testrename", "clean",
            "setthumb", "delthumb", "viewthumb",
            "setcaption", "viewcaption", "set_del_word", "rem_del_word", "set_repl_word", "rem_repl_word",
            "genlink", "share", "links", "revoke", "linkchannel",
        ),
    ),
    (
        "box",
        "Vault & downloads",
        (
            "get", "batch", "custom_batch", "leech", "mirror", "set_caption", "see_caption", "del_caption", "set_thumb", "view_thumb", "see_thumb", "del_thumb", "delete_thumb", ),
    ),
    (
        "music",
        "Music (voice chat)",
        ("play", "playnext", "pause", "resume", "skip", "stop", "end", "resetplayer",
         "queue", "q", "nowplaying", "voicehealth", "leave", "loop", "shuffle", "clearqueue", "clear",
         "remove", "move", "jump", "replay", "seek", "fw", "bw", "seekback", "volume", "volumeup", "volumedown", "history",
         "saveplaylist", "playlist", "playlists", "deleteplaylist", ),
    ),
    (
        "lock",
        "Moderation",
        (
            "warn", "warnings", "unwarn", "mute", "unmute", "kick", "ban", "unban",
            "lock", "unlock", "locks", "locktypes", "allowlist", "rmallowlist", "rmallowlistall", "tban", "tmute", "dban", "dmute", "dkick", "sban", "smute", "skick", "kickme",
            "resetallwarns", "dwarn", "swarn", "rmwarn", "resetwarn", "resetrules", "purge", "note", "approve", "unapprove", "approval", "approved", "addblocklist", "rmblocklist", "unblocklistall", "rmblocklistall", "blocklist", "blocklistmode", "blocklistdelete", "setblocklistreason", "resetblocklistreason", "cleanservice", "cleancommand", "keepcommand", "antispam", "modlog", "flood", "setflood", "setfloodtimer", "floodmode", "clearflood", "warns",
        ),
    ),
    (
        "shield",
        "Group management",
        (
            "settings", "rules", "setrules", "pin", "unpin", "admins",
            "promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror",
            "fedreason", "fednotif", "quietfed", "fedpromote", "feddemote", "feddemoteme", "fedtransfer", "newfed", "renamefed", "delfed", "myfeds", "fedinfo", "fedadmins", "joinfed", "leavefed", "chatfed",
            "actiontopic", "setactiontopic", "newtopic", "renametopic", "closetopic", "reopentopic", "warnlimit", "resetwarns", "lockdown",
            "filter", "filters", "stopfilter",
            "setwelcome", "welcome", "goodbye",
        ),
    ),
    (
        "fire",
        "Community & premium",
        (
            "report", "reports", "appeal",
            "post", "verify",
            "premium", "myplan", "plans", "addpremium", "delpremium", "premiumusers",
        ),
    ),
    (
        "search",
        "Clones",
        ("clone", "panel", "mybots", "delclone", "clonestats"),
    ),
    (
        "bot",
        "Operations (owner)",
        (
            "restart", "bstats", "mychats", "massban", "broadcast", "watchdog", "plugins", "plugin", "events", "errors", "db",
            "setlog", "log", "sudo", "addsudo", "delsudo", "sudolist", "sudoperms",
        ),
    ),
)


def section_slug(title: str) -> str:
    """``Vault & downloads`` -> ``vault-downloads``, for callback data."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def help_visible(commands, active: set[str] | None) -> list[str]:
    """The commands of a section that this deployment really registered."""
    return [
        name
        for name in commands
        if name and (active is None or name in active or name in BUILTIN)
    ]


def help_screen(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
    """The command reference: one table, one button per section.

    *active* is the set of commands the registry actually registered. A plugin
    that could not start (music without a session string) must not appear in the
    reference — an entry for a command that does not exist is the same lie as a
    fake command — so the table is built from what really answered.

    It stays a *rich* message: a native table, a heading and a footer. Editing
    keeps it that way, because the Bot API can edit a rich message too.
    """
    if theme.worker_plugins is not None:
        from .workers import overview
        return overview(user, theme, active=active, help_mode=True)
    rows: list[tuple[str, str]] = []
    for icon, title, commands in HELP_SECTIONS:
        visible = help_visible(commands, active)
        if not visible:
            continue
        rows.append(
            (markup(f"{theme.emoji(icon)} {rich_esc(title)}"), str(len(visible)))
        )
    blocks = [
        rich_heading(f"{theme.emoji('sparkles')} Help", 2),
        rich_note(
            "<b>What would you like to do?</b>\n"
            "Choose a category to explore its tools and how to use them.\n"
            "<b>All commands accept / ! . # $ % &amp; ?</b> — for example, "
            "<code>!help</code>, <code>.play</code>, <code>?settings</code>. "
            "Permissions and plugin availability still apply."
        ),
    ]
    if rows:
        blocks.append("")
        blocks.append(kv_table(rows, headers=("Section", "Commands")).block())
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            "Tap a category below · <code>/help play</code> finds a command directly."
        )
    )
    return Screen("\n".join(blocks), _help_keyboard(active, theme=theme))


def _help_keyboard(active: set[str] | None, *, theme=None) -> InlineKeyboardMarkup:
    theme = theme or Theme()
    rows: list[list[Button]] = []
    row: list[Button] = []
    for icon, title, commands in HELP_SECTIONS:
        if not help_visible(commands, active):
            continue
        row.append(theme.button(title, icon=icon, callback_data=f"help:{section_slug(title)}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([theme.button("Back to menu", icon="back", callback_data=keyboards.CB_HOME)])
    return InlineKeyboardMarkup(rows)


HELP_PAGE_SIZE = 8


def help_section_screen(title: str, user, theme: Theme, *, active: set[str] | None = None, page: int = 0) -> Screen:
    """One section of the reference, with a sentence per command."""
    from ..platform.menu import DESCRIPTIONS

    if title is None:
        return help_screen(user, theme, active=active)
    icon, commands = "help", ()
    for section_icon, section_title, section_commands in HELP_SECTIONS:
        if section_title == title:
            icon, commands = section_icon, section_commands
            break
    visible = [name for name in help_visible(commands, active) if name in DESCRIPTIONS]
    pages = max(1, (len(visible) + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)
    page = min(max(0, page), pages - 1)
    selected = visible[page * HELP_PAGE_SIZE:(page + 1) * HELP_PAGE_SIZE]
    blocks = [
        rich_heading(f"{theme.emoji(icon)} {title}", 2),
        rich_note(
            {
                "Essentials": "Your everyday shortcuts. Start here, check your status or get help.",
                "Moderation": "Keep your community safe. Moderation actions require the appropriate group permissions.",
                "Group management": "Shape your group’s rules and welcome experience. Settings changes require group-admin permissions.",
                "Operations (owner)": "System controls for the bot owner. Delegated diagnostics are limited to explicitly granted access.",
                "Clones": "Create and manage your own bot workspace. Creation and startup require an active Premium entitlement.",
                "Music (voice chat)": "Build your queue and control playback. Availability depends on this group’s plugin and player settings.",
                "Vault & downloads": "Save, find and retrieve your files. Use private chat for personal file details.",
                "Encoding & files": "Prepare your media, refine filenames and manage share links.",
                "Community & premium": "Community tools, reports and your plan. Administrative actions stay permission-protected.",
            }.get(title, "Explore the tools below. Each action checks the permissions it needs.")
            if visible
            else "Nothing in this section is available in this deployment."
        ),
    ]
    if visible:
        table = Table(
            headers=("Command", "What it does"),
            rows=tuple(
                (markup(f"<code>/{rich_esc(name)}</code>"), rich_esc(DESCRIPTIONS[name]))
                for name in selected
            ),
            aligns=("left", "left"),
            max_column=44,
            total_width=58,
        )
        blocks.append("")
        blocks.append(table.block())
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            f"Page {page + 1} of {pages} · All commands accept / ! . # $ % &amp; ? · Choose another category or return to your workspace."
        )
    )
    return Screen("\n".join(blocks), _section_keyboard(title, page, pages, theme=theme))


def _section_keyboard(title=None, page=0, pages=1, *, theme=None) -> InlineKeyboardMarkup:
    theme = theme or Theme()
    navigation = []
    if title and pages > 1:
        buttons = []
        slug = section_slug(title)
        if page > 0:
            buttons.append(theme.button("Previous", icon="back", callback_data=f"help:{slug}:{page - 1}"))
        if page + 1 < pages:
            buttons.append(theme.button("Next", icon="arrow", callback_data=f"help:{slug}:{page + 1}", style=ButtonStyle.PRIMARY))
        navigation.append(buttons)
    return InlineKeyboardMarkup(
        navigation + [
            [
                theme.button(
                    "All sections", icon="folder",
                    callback_data=f"help:{ALL_SECTIONS}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [theme.button("Back to menu", icon="back", callback_data=keyboards.CB_HOME)],
        ]
    )


def _section_builder(title: str, page: int = 0):
    def build(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
        return help_section_screen(title, user, theme, active=active, page=page)

    return build


def info_screen(user, theme: Theme, *, active: set[str] | None = None) -> Screen:
    if theme.worker_plugins is not None:
        from .workers import profile_screen
        return profile_screen(user, theme, active=active)
    user_id = getattr(user, "id", None)
    language = (getattr(user, "language_code", None) or "").strip() or "not reported"
    premium = getattr(user, "is_premium", None)
    premium_text = "yes" if premium else ("no" if premium is False else "not reported")

    rows = [
        ("Name", rich_esc(display_name(user) or "not shared")),
        ("Username", _username(user)),
        (
            "User ID",
            f"<code>{int(user_id)}</code>" if isinstance(user_id, int) else "unknown",
        ),
        ("Language", rich_esc(language)),
        ("Telegram Premium", premium_text),
    ]

    text = (
        rich_heading(f"{theme.emoji('crown')} Your profile", 2)
        + "\n"
        + f"{theme.emoji('user')} This is what Telegram shares with the bot."
        + "\n"
        + kv_table(rows).block()
        + "\n"
        + rich_hr()
        + rich_footer("Telegram profile details are read live. Meiko Premium is separate; use /myplan to check your plan.")
    )
    return Screen(text, keyboards.info_keyboard(user_id if isinstance(user_id, int) else None, theme=theme))


def _section_of(command: str) -> str | None:
    """Which help section a command lives in, or ``None`` if it is unfiled."""
    for _icon, title, commands in HELP_SECTIONS:
        if command in commands:
            return title
    return None


def help_lookup_screen(
    argument: str, user, theme: Theme, *, active: set[str] | None = None
) -> Screen:
    """``/help <something>``: one command, or one section, without the tapping.

    A name is matched against the section titles and against every command the
    menu knows. An unknown name answers with the overview instead of a dead end,
    and a command whose plugin is switched off says so — "not available here" is
    more useful than a description of a command that will not answer.
    """
    from ..platform.menu import DESCRIPTIONS

    query = (argument or "").strip().lstrip("/!.#$%&?").lower()[:64]
    if theme.worker_plugins is not None:
        from .workers import lookup
        return lookup(argument, user, theme, active=active)
    for _icon, title, commands in HELP_SECTIONS:
        if query and query in {title.lower(), section_slug(title)}:
            return _section_builder(title)(user, theme, active=active)
    if query and query not in DESCRIPTIONS:
        # Short category names should work without knowing the display title.
        aliases = {"music": "Music (voice chat)", "vault": "Vault & downloads",
                   "media": "Encoding & files", "groups": "Group management"}
        title = aliases.get(query)
        if title:
            return help_section_screen(title, user, theme, active=active)
        candidates = sorted(name for name in DESCRIPTIONS
                            if help_visible((name,), active) and _section_of(name))
        matches = [name for name in candidates if query in name] if len(query) >= 3 else []
        if not matches and len(query) >= 3:
            matches = difflib.get_close_matches(query, candidates, n=6, cutoff=0.65)
        matches = matches[:6]
        if matches:
            body = (
                rich_heading("Find your next action", 2) + "\n"
                + rich_note(f"Tools matching <b>{rich_esc(query)}</b>. Use <code>/help command</code> for a closer look.")
                + "\n" + Table(headers=("Command", "What it does"), rows=tuple(
                    (markup(f"<code>/{name}</code>"), DESCRIPTIONS[name]) for name in matches
                )).block()
            )
            titles = list(dict.fromkeys(_section_of(name) for name in matches))
            buttons = [[theme.button(title, icon="folder", callback_data=f"help:{section_slug(title)}")]
                       for title in titles if title]
            buttons.append([theme.button("All categories", icon="folder", callback_data=f"help:{ALL_SECTIONS}"),
                            theme.button("Menu", icon="home", callback_data=keyboards.CB_HOME)])
            return Screen(body, InlineKeyboardMarkup(buttons))
    if query not in DESCRIPTIONS:
        body = (
            rich_heading(f"{theme.emoji('sparkles')} Help", 2)
            + "\n"
            + rich_note(
                f"No command or section called <code>{rich_esc(query)}</code>."
                if query
                else "Send <code>/help &lt;command&gt;</code> for one command, "
                "or tap a section."
            )
            + "\n"
            + rich_hr()
            + rich_footer(
                f"{theme.emoji('help')} <code>/help</code> lists the sections; "
                "<code>/menu</code> has the buttons."
            )
        )
        return Screen(body, _section_keyboard(theme=theme))

    available = bool(help_visible((query,), active))
    section = _section_of(query)
    rows = [
        ("Command", markup(f"<code>/{rich_esc(query)}</code>")),
        ("What it does", rich_esc(DESCRIPTIONS[query])),
        ("Section", rich_esc(section or "unfiled")),
        (
            "Available here",
            "yes" if available else "no — the plugin is switched off",
        ),
    ]
    body = (
        rich_heading(f"/{query}", 2)
        + "\n\n"
        + kv_table(rows).block()
        + "\n"
        + (
            "\n" + rich_note(f"Tap <b>{rich_esc(section)}</b> for the rest of its commands.")
            if section and available
            else ""
        )
        + "\n"
        + rich_hr()
        + rich_footer(
            f"{theme.emoji('help')} <code>/help</code> lists every section."
        )
    )
    rows: list[list[Button]] = []
    if section and available:
        rows.append([theme.button(section, icon="folder", callback_data=f"help:{section_slug(section)}")])
    rows.append(
        [
            theme.button("All sections", icon="folder", callback_data=f"help:{ALL_SECTIONS}"),
            theme.button("Menu", icon="home", callback_data=keyboards.CB_HOME),
        ]
    )
    return Screen(body, InlineKeyboardMarkup(rows))


# Callback data -> screen builder, used by the callback router.
SCREENS: dict[str, Callable[..., Screen]] = {
    keyboards.CB_HOME: welcome_screen,
    keyboards.CB_HELP: help_screen,
    keyboards.CB_INFO: info_screen,
}
#: Callback data that returns to the overview from a section screen.
ALL_SECTIONS = "all"
SCREENS[f"help:{ALL_SECTIONS}"] = help_screen
for _icon, _title, _commands in HELP_SECTIONS:
    SCREENS[f"help:{section_slug(_title)}"] = _section_builder(_title)
    for _page in range(max(1, (len(_commands) + HELP_PAGE_SIZE - 1) // HELP_PAGE_SIZE)):
        SCREENS[f"help:{section_slug(_title)}:{_page}"] = _section_builder(_title, _page)


def ping_screen(monitor, theme: Theme) -> Screen:
    """Live health, as a Telegram reply (works on a Background Worker)."""
    if monitor is None:
        return Screen(
            rich_heading(f"{theme.emoji('bolt')} Ping", 2)
            + "\n"
            + rich_note("Health tracking is not running."),
            keyboards.info_keyboard(theme=theme),
        )

    snapshot = monitor.snapshot()
    rows = [
        ("State", snapshot.state),
        ("Uptime", format_uptime(snapshot.uptime_seconds)),
        (
            "Telegram latency",
            f"{snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "no probe yet",
        ),
        ("Probes", f"{snapshot.probes} ({snapshot.failures} failed)"),
    ]
    if snapshot.seconds_since_activity is not None:
        rows.append(("Last update", f"{format_uptime(snapshot.seconds_since_activity)} ago"))
    # The error goes below the table, not in it: a table cell is clipped to the
    # column width, and "ConnectionResetError: link dow…" is not a useful report.
    error_line = (
        f"Last error: <code>{rich_esc(snapshot.last_error[:200])}</code>"
        if snapshot.last_error
        else ""
    )

    text = (
        rich_heading(f"{theme.emoji('bolt')} Ping", 2)
        + "\n"
        + f"{theme.emoji('bolt')} Live status of this instance."
        + "\n"
        + kv_table(rows).block()
        + ("\n" + error_line if error_line else "")
        + "\n"
        + rich_hr()
        + rich_footer("The watchdog probes Telegram on a timer.")
    )
    return Screen(text, keyboards.info_keyboard(theme=theme))
