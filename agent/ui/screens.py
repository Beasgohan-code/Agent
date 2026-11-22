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
        ("start", "help", "lang", "menu", "about", "status", "alive", "uptime", "ping", "cancel", "jobs", "owner",
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
        ('mute', 'unmute', 'kick', 'ban', 'unban', 'tban', 'tmute', 'dban', 'dmute', 'dkick', 'sban', 'smute', 'skick', 'kickme', 'afk', 'userstats', 'recentactivity', 'setchatname', 'setchatdescription', 'setchatphoto', 'privaterules', 'resetrules', 'purge', 'spurge', 'cleanservice', 'cleancommand', 'keepcommand', 'antispam', 'modlog'),
    ),
    (
        "shield",
        "Group management",
        ('settings', 'rules', 'setrules', 'pin', 'unpin', 'admins', 'lockdown'),
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
    ('lock', 'Blacklist', ('blocklist', 'addblocklist', 'rmblocklist', 'unblocklistall', 'rmblocklistall', 'blocklistmode', 'blocklistdelete', 'setblocklistreason', 'resetblocklistreason')),
    ('wave', 'Welcome & goodbye', ('setwelcome', 'welcome', 'goodbye')),
    ('shield', 'Federations', ('fedreason', 'fednotif', 'quietfed', 'fedpromote', 'feddemote', 'feddemoteme', 'fedtransfer', 'newfed', 'renamefed', 'delfed', 'myfeds', 'fedinfo', 'fedadmins', 'joinfed', 'leavefed', 'chatfed')),
    ('warn', 'Warnings', ('warn', 'warnings', 'warns', 'unwarn', 'dwarn', 'swarn', 'rmwarn', 'resetwarn', 'resetwarns', 'resetallwarns', 'warnlimit', 'warnmode', 'warntime', 'note')),
    ('lock', 'Locks', ('lock', 'unlock', 'locks', 'locktypes', 'allowlist', 'rmallowlist', 'rmallowlistall')),
    ('shield', 'Anti-flood', ('flood', 'setflood', 'setfloodtimer', 'floodmode', 'clearflood')),
    ('filter', 'Filters', ('filter', 'filters', 'stopfilter')),
    ('folder', 'Topics', ('newtopic', 'renametopic', 'closetopic', 'reopentopic', 'actiontopic', 'setactiontopic')),
    ('crown', 'Administrator tools', ('promote', 'demote', 'tpromote', 'fullpromote', 'adminlist', 'admincache', 'anonadmin', 'adminerror', 'adminbox', 'admincount', 'rights')),
    ('user', 'Mentions', ('tagall', 'all', 'etagall', 'eall', 'tagabort', 'allsettings', 'tagstats')),
    ('check', 'Approvals', ('approve', 'unapprove', 'approval', 'approved')),
)



# Feature-level guidance follows the actual native handlers, not upstream aliases.
MODULE_HELP = {
    'Administrator tools': {
        'intro': 'Inspect group administration and manage administrator privileges with live Telegram permission checks. Read the scope before granting authority.',
        'usage': {'promote': '/promote <member> [title] or reply /promote [title]', 'demote': '/demote <member>', 'tpromote': '/tpromote <member> <duration> or /tpromote status', 'fullpromote': '/fullpromote <member> then explicit confirmation', 'adminlist': '/adminlist', 'admincache': '/admincache', 'admincount': '/admincount', 'adminbox': '/adminbox', 'rights': '/rights [member]', 'anonadmin': '/anonadmin [on|off]', 'adminerror': '/adminerror [on|off]'},
        'notes': 'Ordinary promotion grants limited rights capped by the caller and bot; it does not grant delegation or anonymous identity. Custom titles allow up to 16 characters, with no control/format characters; Telegram may reject emoji. Full promotion is group-owner-only and can grant delegation, including Add administrators, only after explicit confirmation and capped by bot rights. Temporary promotion needs durable tracking and a running recovery worker; expiry is not an offline guarantee. Administrator snapshots describe the current Telegram response, never a cached permission grant. Inspect current state before retrying unconfirmed operations.',
        'examples': (('promote', '/promote @member Team lead'), ('adminlist', '/adminlist'), ('tpromote', '/tpromote status')),
    },
    'Mentions': {
        'intro': 'Mention the members returned by Telegram in paced batches, or inspect and stop the current mention run. No enrollment or opt-in is required.',
        'usage': {'tagall': '/tagall [optional message]', 'all': '/all [optional message] or @all', 'etagall': '/etagall [optional message]', 'eall': '/eall [optional message] or @eall', 'tagabort': '/tagabort', 'allsettings': '/allsettings', 'tagstats': '/tagstats'},
        'notes': 'Current Manage chat administrator permission is required. Normal mentions use clickable first names, not member IDs; emoji variants use emoji labels. Without custom text there is no automatic heading. Requests use 20 mentions per message with a pause of 5 seconds. Telegram may return only part of the group: this is not a complete member roster. The snapshot is capped at 2000 returned entries. Stop cannot recall a message already in flight; Resume/Stop controls check current permissions.',
        'examples': (('tagall', '/tagall'), ('eall', '@eall'), ('tagabort', '/tagabort')),
    },
    'Approvals': {
        'intro': 'Manage automatic anti-spam exemptions for individual members and inspect this group’s approved-member list.',
        'usage': {'approve': '/approve <member>', 'unapprove': '/unapprove <member>', 'approval': '/approval <member>', 'approved': '/approved [page]'},
        'notes': 'Current Manage chat permission is required. Use a positive ID, @username, text mention or visible personal reply, without extra arguments. Approval exempts a member from automatic anti-spam actions, not manual moderation. It does not grant Telegram administrator rights. Removing approval does not ban, kick or mute the member. Status and lists are visible to the chat; successful confirmation describes stored state, not live enforcement readiness.',
        'examples': (('approve', '/approve @member'), ('approval', '/approval @member'), ('approved', '/approved 1')),
    },
    'Warnings': {
        'intro': 'Record and review member warnings, remove active warnings and configure future escalation. Warning history and Telegram bans or mutes are separate state.',
        'usage': {'warn': '/warn <member> [reason] or reply /warn [reason]', 'warns': '/warns <member>', 'warnings': '/warnings <member>', 'warnlimit': '/warnlimit <1–20> [mute|kick|ban] or /warnlimit off', 'warnmode': '/warnmode mute|kick|ban', 'warntime': '/warntime off or <duration>', 'rmwarn': '/rmwarn <member>', 'unwarn': '/unwarn <member>', 'resetwarn': '/resetwarn <member>', 'resetwarns': '/resetwarns <member>', 'resetallwarns': '/resetallwarns confirm', 'dwarn': 'Reply /dwarn [reason]', 'swarn': '/swarn <member> [reason]', 'note': '/note <member> <text>'},
        'notes': 'Use a positive ID, @username or a visible personal reply for a member. Restrict members permission is required for warning changes; delete variants also require Delete messages. Removing warnings retains history and never unbans or unmutes. Expiry affects new warnings only; expired warnings stop counting but remain in history. Group resets require explicit confirmation. Partial or unconfirmed results must be inspected before a new request.',
        'examples': (('warnlimit', '/warnlimit 3 mute'), ('warntime', '/warntime 7d'), ('warns', '/warns 123456789')),
    },
    'Locks': {
        'intro': 'Choose which supported message types should be removed from this group. Inspect the current locks and available types before changing protection.',
        'usage': {'lock': '/lock <type> [type ...]', 'unlock': '/unlock <type> [type ...]', 'locks': '/locks', 'locktypes': '/locktypes'},
        'notes': 'Administrators are exempt. Matching non-admin messages are deleted before blacklist handling; locks do not apply custom punishments or warning modes. The all selector includes only supported types. Invite-link detection covers explicit private invites, not every public username. Live rights and configuration checks still apply.',
        'examples': (('lock', '/lock gif video sticker'), ('unlock', '/unlock video'), ('locktypes', '/locktypes')),
    },
    'Anti-flood': {
        'intro': 'Configure consecutive-message and timed-window flood limits, the member action and optional message cleanup.',
        'usage': {'flood': '/flood', 'setflood': '/setflood <2–1000>|off', 'setfloodtimer': '/setfloodtimer <2–1000> <30s–1d> or /setfloodtimer off', 'floodmode': '/floodmode ban|mute|kick or /floodmode tban|tmute <duration>', 'clearflood': '/clearflood on|off'},
        'notes': 'Counters are bounded and process-local; restarts do not preserve the current counting window. Staff and approved members are exempt. Timed punishments accept 30s–365d; window length is limited to one day. Live administrator rights are required for settings changes, and Telegram rights are required for enforcement. Enabling cleanup does not prove every deletion succeeded.',
        'examples': (('setfloodtimer', '/setfloodtimer 10 30s'), ('floodmode', '/floodmode tmute 5m'), ('flood', '/flood')),
    },
    'Filters': {
        'intro': 'Save a named reply, browse this group’s filters, preview the full reply and remove filters that are no longer needed.',
        'usage': {'filter': '/filter <name> <reply text>', 'filters': '/filters [page] or /filters show <name>', 'stopfilter': '/stopfilter <name>'},
        'notes': 'Saved replies are plain text, not executable templates or arbitrary HTML. Previewing a reply shows it in the current chat. Administrator checks protect changes; storing a reply is not proof that it was delivered to any member.',
        'examples': (('filter', '/filter hello Welcome!'), ('filters', '/filters show hello'), ('stopfilter', '/stopfilter hello')),
    },
    'Topics': {
        'intro': 'Create, rename, close and reopen forum topics, or choose where welcome and goodbye messages should go.',
        'usage': {'newtopic': '/newtopic <name>', 'renametopic': '/renametopic <name>', 'closetopic': '/closetopic', 'reopentopic': '/reopentopic', 'actiontopic': '/actiontopic', 'setactiontopic': '/setactiontopic'},
        'notes': 'Use a forum supergroup with Manage topics permission for both caller and bot. Run topic changes in the relevant topic. Names allow 1–128 UTF-16 units without control characters. Settings remain shared across topics. Set the greeting destination from the desired topic; use General to return there. Failed delivery does not fall back into another topic. Topic deletion is not implemented.',
        'examples': (('newtopic', '/newtopic Announcements'), ('actiontopic', '/actiontopic'), ('setactiontopic', '/setactiontopic')),
    },
    'Blacklist': {
        'intro': 'Manage blocked text, filenames and sender-name patterns in this group. Administrators choose triggers, the member action and whether matching messages are deleted.',
        'usage': {
            'blocklist': '/blocklist',
            'addblocklist': '/addblocklist <trigger> [reason] or /addblocklist (word "quoted phrase") [reason]',
            'rmblocklist': '/rmblocklist <trigger> or /rmblocklist (word "quoted phrase")',
            'blocklistmode': '/blocklistmode nothing|warn|ban|mute|kick|tban|tmute [duration]',
            'blocklistdelete': '/blocklistdelete on|off',
            'setblocklistreason': '/setblocklistreason <reason>',
            'resetblocklistreason': '/resetblocklistreason',
            'unblocklistall': '/unblocklistall confirm',
            'rmblocklistall': '/rmblocklistall confirm',
        },
        'notes': 'Automatic detection: matching messages use the configured action. Staff and approved members are exempt. Modes: nothing means no member punishment; warn adds a warning; ban, mute and kick act on the member; tban and tmute require a duration such as 1h. Message deletion is controlled separately. Triggers support case/accent-insensitive globs; quote phrases and use parentheses for batches of up to 20. Sticker-specific blacklist commands are not implemented.',
        'examples': (('addblocklist', '/addblocklist (spam rude) Unwanted content'), ('blocklistmode', '/blocklistmode warn'), ('blocklistdelete', '/blocklistdelete on')),
    },
    'Welcome & goodbye': {
        'intro': 'Configure greetings for real membership joins and farewells for leaves. Group administrators control the text and whether each greeting is enabled.',
        'usage': {'setwelcome': '/setwelcome <text>', 'welcome': '/welcome [on|off]', 'goodbye': '/goodbye [on|off|text]'},
        'notes': 'Placeholders: {mention} links to the member, {name} is their first name, {chat} is the group title and {count} is the available member count. Templates are plain text; arbitrary HTML is not enabled. Greetings depend on supported membership updates and current permissions.',
        'examples': (('setwelcome', '/setwelcome Welcome {mention} to {chat}!'), ('welcome', '/welcome on'), ('goodbye', '/goodbye Goodbye {name}!')),
    },
    'Federations': {
        'intro': 'Organize federation ownership, administrators and group enrollment. Only the current Telegram chat owner can join or leave a federation for that group.',
        'usage': {'newfed': '/newfed <name>', 'renamefed': '/renamefed <name>', 'joinfed': '/joinfed <federation_id>', 'leavefed': '/leavefed', 'chatfed': '/chatfed', 'myfeds': '/myfeds [page]'},
        'notes': 'Federation ownership and delegated roles are checked for each operation. Ban synchronization is not available: these tools manage metadata and enrollment, not network-wide bans. Notification preferences do not mean delivery is implemented.',
        'examples': (('newfed', '/newfed My community'), ('myfeds', '/myfeds'), ('chatfed', '/chatfed')),
    },
}


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


HELP_CATEGORY_PAGE_SIZE = 8


GROUP_HELP_MODULES = ('Group management', 'Moderation', 'Warnings', 'Administrator tools',
                      'Mentions', 'Approvals', 'Blacklist', 'Welcome & goodbye',
                      'Federations', 'Locks', 'Anti-flood', 'Filters', 'Topics')


def _help_categories(active):
    group_commands = tuple(dict.fromkeys(command for _, title, commands in HELP_SECTIONS
                                        if title in GROUP_HELP_MODULES for command in commands))
    return [(icon, title, group_commands if title == 'Group management' else commands)
            for icon, title, commands in HELP_SECTIONS
            if (title == 'Group management' or title not in GROUP_HELP_MODULES)
            and help_visible(group_commands if title == 'Group management' else commands, active)]


def help_module_screen(title, user, theme, *, active=None):
    """Read-only task navigation between the module root and command guides."""
    if theme.worker_plugins is not None:
        from .workers import overview
        return overview(user, theme, active=active, help_mode=True)
    rows, buttons = [], []
    if title == 'Group management':
        for icon, child, commands in HELP_SECTIONS:
            if child not in GROUP_HELP_MODULES:
                continue
            visible = help_visible(commands, active)
            if not visible:
                continue
            label = 'Group settings' if child == title else child
            route = 'help:group-management:0' if child == title else f'help:{section_slug(child)}'
            rows.append((label, str(len(visible))))
            buttons.append(theme.button(label, icon=icon, callback_data=route))
        heading, icon = 'Group management', 'shield'
        note = 'Choose a feature, then a command. Opening help does not change settings or grant administrator rights.'
    else:
        music = next(commands for _, section, commands in HELP_SECTIONS if section == 'Music (voice chat)')
        visible = help_visible(music, active)
        tasks = (('play', 'Playback'), ('queue', 'Queue'), ('playlists', 'Playlists'),
                 ('loop', 'Repeat'), ('volume', 'Volume'), ('voicehealth', 'Player health'),
                 ('pause', 'Pause'), ('resume', 'Resume'), ('stop', 'Stop'))
        for command, label in tasks:
            if command in visible:
                rows.append((label, '/' + command))
                buttons.append(theme.button(label, icon='music', callback_data=f'help:command:{command}'))
        if visible:
            buttons.append(theme.button('All music commands', icon='search', callback_data='help:music-voice-chat:0'))
        heading, icon = 'Music', 'music'
        note = 'Choose a task to read its help. Opening this page does not start playback, stop the player or change the queue. Live plugin and permission checks still apply.'
    keys = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keys.append([theme.button('All modules', icon='back', callback_data='help:all', style=ButtonStyle.PRIMARY)])
    keys.append([theme.button('Menu', icon='home', callback_data=keyboards.CB_HOME)])
    from .tables import panel
    body = panel(heading, icon=theme.emoji(icon), subtitle='Choose what you want to do',
                 table=kv_table(rows, headers=('Feature', 'Commands')) if rows else None,
                 lines=[] if rows else ['No commands in this module are currently registered.'], note=note)
    return Screen(body, InlineKeyboardMarkup(keys))


def help_screen(user, theme: Theme, *, active: set[str] | None = None, page: int = 0) -> Screen:
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
    categories = _help_categories(active)
    pages = max(1, (len(categories) + HELP_CATEGORY_PAGE_SIZE - 1) // HELP_CATEGORY_PAGE_SIZE)
    page = min(max(0, page), pages - 1)
    rows: list[tuple[str, str]] = []
    for icon, title, commands in categories[page * HELP_CATEGORY_PAGE_SIZE:(page + 1) * HELP_CATEGORY_PAGE_SIZE]:
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
            "Choose a module, then a feature or command for its details.\n"
            "<b>All commands accept / ! . # $ % &amp; ?</b> — for example, "
            "<code>!help</code>, <code>.play</code>, <code>?settings</code>. "
            "Permissions and plugin availability still apply."
        ),
    ]
    if rows:
        blocks.append("")
        blocks.append(kv_table(rows, headers=("Module", "Commands")).block())
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            f"Page {page + 1} of {pages} · {len(categories)} modules · Tap a module below or use <code>/help command</code>."
        )
    )
    return Screen("\n".join(blocks), _help_keyboard(active, theme=theme, page=page))


def _help_keyboard(active: set[str] | None, *, theme=None, page=0) -> InlineKeyboardMarkup:
    theme = theme or Theme()
    rows: list[list[Button]] = []
    row: list[Button] = []
    categories = _help_categories(active)
    pages = max(1, (len(categories) + HELP_CATEGORY_PAGE_SIZE - 1) // HELP_CATEGORY_PAGE_SIZE)
    page = min(max(0, page), pages - 1)
    for icon, title, commands in categories[page * HELP_CATEGORY_PAGE_SIZE:(page + 1) * HELP_CATEGORY_PAGE_SIZE]:
        row.append(theme.button(title, icon=icon, callback_data=f"help:{section_slug(title)}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    paging = []
    if page:
        paging.append(theme.button('Previous modules', icon='back', callback_data=f'help:categories:{page - 1}'))
    if page + 1 < pages:
        paging.append(theme.button('Next modules', icon='arrow', callback_data=f'help:categories:{page + 1}', style=ButtonStyle.PRIMARY))
    if paging:
        rows.append(paging)
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
    guide = MODULE_HELP.get(title)
    blocks = [
        rich_heading(f"{theme.emoji(icon)} {rich_esc(title)}", 2),
        rich_note(
            guide['intro'] if guide and visible else {
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
                (markup(f"<code>{rich_esc(guide['usage'].get(name, '/' + name) if guide else '/' + name)}</code>"), DESCRIPTIONS[name])
                for name in selected
            ),
            aligns=("left", "left"),
            max_column=44,
            total_width=58,
        )
        blocks.append("")
        blocks.append(table.block())
        if guide:
            blocks.append("<b>How it works</b>\n" + rich_esc(guide['notes']))
            examples = [example for name, example in guide['examples'] if name in visible]
            if examples:
                blocks.append('<b>Examples</b>\n' + '\n'.join('<code>' + rich_esc(example) + '</code>' for example in examples))
            blocks.append(rich_note('Group-visible help only. Opening this page does not change settings; administrator permissions are checked when you send a command.'))
    blocks.append("")
    blocks.append(rich_hr())
    blocks.append(
        rich_footer(
            f"Page {page + 1} of {pages} · Tap a command below for details · All commands accept / ! . # $ % &amp; ? · Choose another category or return to your workspace."
        )
    )
    return Screen("\n".join(blocks), _section_keyboard(title, page, pages, theme=theme, commands=selected, active=active))


def _section_keyboard(title=None, page=0, pages=1, *, theme=None, commands=(), active=None) -> InlineKeyboardMarkup:
    theme = theme or Theme()
    navigation = []
    for offset in range(0, len(commands), 2):
        navigation.append([theme.button('/' + name, icon='help', callback_data=f'help:command:{name}')
                           for name in commands[offset:offset + 2]])
    if title and pages > 1:
        buttons = []
        slug = section_slug(title)
        if page > 0:
            buttons.append(theme.button("Previous", icon="back", callback_data=f"help:{slug}:{page - 1}"))
        if page + 1 < pages:
            buttons.append(theme.button("Next", icon="arrow", callback_data=f"help:{slug}:{page + 1}", style=ButtonStyle.PRIMARY))
        navigation.append(buttons)
    if title in GROUP_HELP_MODULES:
        navigation.append([theme.button('Back to Group management', icon='back', callback_data='help:group-management')])
    elif title == 'Music (voice chat)':
        navigation.append([theme.button('Back to Music', icon='back', callback_data='help:music-voice-chat')])
    categories = [category for _, category, _ in _help_categories(active)]
    if title in categories:
        overview_page = categories.index(title) // HELP_CATEGORY_PAGE_SIZE
        if overview_page:
            navigation.append([theme.button('Back to categories', icon='back', callback_data=f'help:categories:{overview_page}')])
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
            if title in ('Group management', 'Music (voice chat)'):
                return help_module_screen(title, user, theme, active=active)
            return _section_builder(title)(user, theme, active=active)
    if query and query not in DESCRIPTIONS:
        # Short category names should work without knowing the display title.
        aliases = {"music": "Music (voice chat)", "vault": "Vault & downloads",
                   "media": "Encoding & files", "groups": "Group management",
                   "federation": "Federations", "greetings": "Welcome & goodbye"}
        title = aliases.get(query)
        if title:
            if title in ('Group management', 'Music (voice chat)'):
                return help_module_screen(title, user, theme, active=active)
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
            buttons = [[theme.button('/' + name, icon='help', callback_data=f'help:command:{name}')
                        for name in matches[offset:offset + 2]] for offset in range(0, len(matches), 2)]
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
        ("What it does", DESCRIPTIONS[query]),
        ("Section", section or "unfiled"),
        (
            "Registered here",
            ("yes — permissions and activation still apply" if active is not None else "not checked — permissions and activation still apply")
            if available else "no — command not registered in this instance",
        ),
    ]
    guide = MODULE_HELP.get(section)
    if guide and available and query in guide['usage']:
        rows.insert(1, ('Syntax', guide['usage'][query]))
    body = (
        rich_heading(f"/{query}", 2)
        + "\n\n"
        + kv_table(rows).block()
        + ("\n" + rich_note(rich_esc(guide['notes'])) if guide and available else '')
        + "\n"
        + (
            "\n" + rich_note(f"Tap <b>{rich_esc(section)}</b> for the rest of its commands.")
            if section and available
            else ""
        )
        + "\n"
        + rich_hr()
        + rich_footer(
            f"{theme.emoji('help')} Viewing help does not run a command or grant permissions. <code>/help</code> lists every section."
        )
    )
    rows: list[list[Button]] = []
    if section and available:
        from ..platform.menu import DESCRIPTIONS
        section_commands = next(commands for _, title, commands in HELP_SECTIONS if title == section)
        visible = [name for name in help_visible(section_commands, active) if name in DESCRIPTIONS]
        page = visible.index(query) // HELP_PAGE_SIZE if query in visible else 0
        rows.append([theme.button('Back to ' + section, icon="back", callback_data=f"help:{section_slug(section)}:{page}")])
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


SCREENS['help:group-management'] = lambda user, theme, active=None: help_module_screen('Group management', user, theme, active=active)
SCREENS['help:music-voice-chat'] = lambda user, theme, active=None: help_module_screen('Music (voice chat)', user, theme, active=active)


def _category_builder(page):
    def build(user, theme, *, active=None):
        return help_screen(user, theme, active=active, page=page)
    return build


for _page in range(max(1, (len(HELP_SECTIONS) + HELP_CATEGORY_PAGE_SIZE - 1) // HELP_CATEGORY_PAGE_SIZE)):
    SCREENS[f'help:categories:{_page}'] = _category_builder(_page)


def _command_help_builder(command):
    def build(user, theme, *, active=None):
        return help_lookup_screen(command, user, theme, active=active)
    return build


# Finite, read-only callbacks. Unknown command bytes never become executable routes.
for _icon, _title, _commands in HELP_SECTIONS:
    for _command in _commands:
        SCREENS[f'help:command:{_command}'] = _command_help_builder(_command)


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
