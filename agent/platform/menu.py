"""The Telegram command menu.

Two things live here: publishing the bot's command list (``set_bot_commands``)
and resetting the chat menu button (``set_chat_menu_button``).

On the button: the Bot API offers three shapes — a web-app launcher, the command
list, or the default. There is **no** "hide it completely" option, so "delete the
menu button" means "stop pointing it at anything custom": the button goes back to
the default command list instead of a web app that no longer exists. That is the
honest boundary, and it is stated in the log line rather than implied.

Scopes are split so the list matches the chat: private and anywhere-commands go
to the default scope, group-only commands (moderation, filters, greetings) go to
the group scope. Nobody needs to see ``/ban`` in a DM.
"""

from __future__ import annotations

import logging
import asyncio
import re
from typing import Iterable

from pyrogram.types import BotCommand

logger = logging.getLogger(__name__)

#: Telegram: 1-32 chars, lowercase letters, digits and underscores only.
VALID_NAME = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_COMMANDS = 100
MAX_DESCRIPTION = 256
SYNC_TIMEOUT = 10.0

#: One line per command, kept short — this is menu text, not documentation.
DESCRIPTIONS: dict[str, str] = {
    # core
    "start": "Open the main menu",
    "help": "Every command, one screen per section",
    "menu": "Open the inline control menu",
    "about": "What this bot is",
    "status": "Live runtime status",
    "cancel": "Stop your jobs, or /cancel job-id for one",
    "jobs": "Your jobs; optionally filter by module (private)",
    "owner": "Owner control panel",
    "ping": "Health and latency of this instance",
    # clone
    "clone": "Clone this bot onto another token",
    "mybots": "Your clones and their controls",
    "panel": "All your clone bots in one controller",
    "delclone": "Delete one of your clones",
    "clonestats": "Clone counts (owner)",
    # moderation
    "lock": "Delete selected non-admin content types",
    "unlock": "Stop deleting selected content types",
    "locks": "View content lock settings",
    "allowlist": "View/add URL-lock domain exemptions",
    "rmallowlist": "Remove URL-lock domain exemptions",
    "rmallowlistall": "Clear domain exemptions (group owner, confirmed)",
    "locktypes": "List supported content lock types",
    "warn": "Warn a member",
    "warnings": "List a member's warnings",
    "warns": "Alias of /warnings",
    "unwarn": "Clear one warning",
    "mute": "Temporarily restrict a member",
    "unmute": "Restore a member's permissions",
    "kick": "Remove a member (they may return)",
    "tban": "Temporarily ban a member",
    "tmute": "Temporarily mute a member",
    "dban": "Ban and delete the replied message",
    "dmute": "Mute and delete the replied message",
    "dkick": "Kick and delete the replied message",
    "sban": "Ban silently; delete related messages",
    "smute": "Mute silently; delete related messages",
    "skick": "Kick silently; delete related messages",
    "kickme": "Leave this group by self-requested kick",
    "ban": "Ban a member",
    "unban": "Lift a ban",
    "spurge": "Silently delete 1–100 preceding message IDs (admin)",
    "purge": "Delete the last N messages",
    "note": "Attach a private note to a member",
    "approve": "Exempt a member from automatic anti-spam",
    "unapprove": "Remove a member approval",
    "approval": "Check a member approval",
    "approved": "List approved members",
    "flood": "Show antiflood settings",
    "setflood": "Set the consecutive-message flood limit",
    "setfloodtimer": "Set the timed flood limit",
    "floodmode": "Set the antiflood action",
    "clearflood": "Toggle flood message cleanup",
    "addblocklist": "Add a text or filename blocklist trigger",
    "rmblocklist": "Remove a blocklist trigger",
    "unblocklistall": "Clear triggers with chat-owner confirmation",
    "rmblocklistall": "Alias for /unblocklistall",
    "blocklist": "Show blocklist settings and triggers",
    "blocklistmode": "Set the blocklist action",
    "blocklistdelete": "Toggle blocked-message deletion",
    "setblocklistreason": "Set the default blocklist reason",
    "resetblocklistreason": "Reset the default blocklist reason",
    "cleancommand": "Delete recognized commands after handling (group)",
    "keepcommand": "Disable recognized-command cleanup (group)",
    "actiontopic": "Show the welcome/goodbye topic destination",
    "setactiontopic": "Route greetings to the current forum topic",
    "newtopic": "Create a forum topic (Manage topics required)",
    "renametopic": "Rename the current forum topic",
    "closetopic": "Close the current forum topic",
    "reopentopic": "Reopen the current forum topic",
    "cleanservice": "Choose which group service notices to delete",
    "antispam": "Anti-spam policy for this group",
    "modlog": "Recent moderation actions",
    "fedpromote": "Invite a federation administrator",
    "feddemote": "Remove a federation administrator",
    "feddemoteme": "Resign from a federation",
    "fedreason": "Store the federation reason requirement (enforcement pending)",
    "fednotif": "Store the owner notification preference (delivery pending)",
    "quietfed": "Store the chat federation silence preference (delivery pending)",
    "fedtransfer": "Invite a new federation owner",
    "newfed": "Create your federation",
    "renamefed": "Rename your federation",
    "delfed": "Delete your federation with confirmation",
    "myfeds": "List federations you administer",
    "fedinfo": "Look up a federation by ID",
    "fedadmins": "List federation administrators",
    "joinfed": "Join this chat to a federation (chat owner)",
    "leavefed": "Leave this chat federation (chat owner)",
    "chatfed": "Show this chat federation",
    # group management
    "settings": "This group's live settings panel",
    "rules": "Show this group's rules",
    "setrules": "Publish this group's rules",
    "pin": "Pin the replied message",
    "unpin": "Unpin a message, or all of them",
    "promote": "Promote a group member with optional 1–16 character title",
    "demote": "Demote an editable administrator",
    "adminlist": "List current group administrators",
    "admincache": "Refresh the administrator snapshot",
    "anonadmin": "Allow anonymous group-admin checks (unsafe)",
    "adminerror": "Toggle admin permission-denial messages",
    "admins": "List this group's administrators",
    "warntime": "Set expiry for new warnings: off or 1m–366d",
    "warnmode": "Set warning escalation mode: mute, kick or ban",
    "warnlimit": "Warnings needed to trigger an action",
    "resetwarns": "Clear all warnings for a member",
    "lockdown": "Restrict the group to administrators",
    # filestore

    "get": "Re-send a file from your vault",
    "batch": "Save a run of files into your vault",
    "custom_batch": "Owner: archive range or selected-message link (private)",
    "check": "Everything about one vault entry",


    # leech
    "set_thumb": "Set personal upload thumbnail (reply to photo)",
    "view_thumb": "View personal upload thumbnail",
    "see_thumb": "View personal upload thumbnail",
    "del_thumb": "Remove personal upload thumbnail",
    "delete_thumb": "Remove personal upload thumbnail",
    "leech": "Download an http(s) link and send it here",
    "mirror": "Download a link and keep it in your vault",

    # music (voice chat)
    "play": "Stream audio into the voice chat",
    "pause": "Pause playback",
    "resume": "Resume playback",
    "skip": "Play the next track",
    "stop": "Stop and clear the queue",
    "queue": "Browse the playback queue: /queue [page]",
    "nowplaying": "What this group is playing",
    "alive": "Live bot health and uptime",
    "uptime": "Process uptime and Telegram probe health",
    "voicehealth": "Admin-only cached voice diagnostics for this group",
    "q": "Browse the music queue: /q [page]",
    "end": "Stop playback and clear the music queue",
    "resetplayer": "Reset this group's player and queue",
    "playnext": "Queue a direct URL or replied media next",
    "loop": "Repeat off, current track or entire queue",
    "shuffle": "Shuffle upcoming music tracks",
    "clear": "Clear upcoming music without stopping playback",
    "clearqueue": "Clear upcoming music tracks",
    "remove": "Remove an upcoming music track by position",
    "move": "Move an upcoming music track",
    "jump": "Start a selected upcoming music track",
    "replay": "Restart the current music track",
    "seek": "Seek to seconds, m:ss or a relative offset",
    "fw": "Fast-forward playback by seconds, minutes or hours",
    "bw": "Rewind playback by seconds, minutes or hours",
    "seekback": "Seek backward within the current track",
    "volume": "View or set voice-chat volume",
    "volumeup": "Increase voice-chat volume by 20 percent",
    "volumedown": "Decrease voice-chat volume by 20 percent",
    "history": "Recent acknowledged music titles this session",
    "saveplaylist": "Save queue; add upcoming to exclude current track",

    "playlist": "Append saved playlist; add preview to inspect titles",
    "playlists": "List your saved playlists in this group",
    "deleteplaylist": "Delete your saved playlist in this group",
    "leave": "Leave the voice chat",
    # reports / posts / security
    "report": "Report a message to the moderators",
    "reports": "Review reports: pages, closed, show or close number",
    "appeal": "Appeal a moderation action",
    "post": "Publish a formatted post",

    "verify": "Mute new members until they verify",
    "premium": "Your tier, its limits and what is left today",
    "myplan": "Your tier and what is left, short form",
    "plans": "Compare the free and premium tiers",
    "addpremium": "Grant premium to a user (owner)",
    "delpremium": "Take premium away (owner)",
    "premiumusers": "Everyone with premium (owner)",
    # filters / welcome
    "filter": "Add a keyword auto-reply",
    "filters": "List this group's filters",
    "stopfilter": "Remove a keyword auto-reply",
    "setwelcome": "Set the welcome message",
    "welcome": "Show or toggle the welcome message",
    "goodbye": "Set or toggle the goodbye message",
    # utilities
    "id": "Show chat and user ids",
    "info": "Details about a member",
    "time": "Current time here and in UTC",
    "repo": "Bot version and information",
    # encoder
    "encode": "Encode a replied video",
    "compress": "Make a replied video smaller (fast preset)",
    "sample": "Cut a short clip from a replied video",
    "toaudio": "Extract audio as MP3, M4A or FLAC",
    "screens": "Create a 4, 9 or 16-frame contact sheet",
    "mediainfo": "Probe a replied video",

    # linkshare
    "linkchannel": "Required channel for share links (Owner, private)",
    "genlink": "Create a signed link for a file",
    "share": "Link a file already in your vault",
    "links": "Browse your links: /links [page]",
    "revoke": "Revoke one of your links",
    # renamer
    "autorename": "Set the filename template",
    "rename": "Rename a replied file",
    "testrename": "Preview a rename",
    "clean": "Tidy a filename",
    "setthumb": "Use a replied image as this chat's thumbnail",
    "delthumb": "Stop attaching a thumbnail",
    "viewthumb": "Show the thumbnail this chat uses",
    "set_del_word": "Add literal words to remove from media names",
    "rem_del_word": "Remove media-name deletion rules",
    "set_repl_word": "Set a literal media-name replacement",
    "rem_repl_word": "Remove a media-name replacement",
    "setcaption": "Set the caption files are sent with",

    "viewcaption": "Show the caption with an example",
    "set_caption": "Set your private upload caption: {filename}, {size}",
    "see_caption": "View your private upload caption",
    "del_caption": "Remove your private upload caption",
    # ops (owner)
    "restart": "Restart the process (owner)",
    "afk": "Toggle your group away status; optional public reason",
    "fullpromote": "Group owner: delegate bot-held group rights; confirm required",
    "adminbox": "Live caller/bot permissions and registered admin tools",
    "userstats": "Live group member count and bot uptime (admin)",
    "recentactivity": "Recent cached group moderation actions (admin)",
    "admincount": "Live administrator count (group admin)",
    "rights": "Read-only current Telegram admin-rights card (admin)",
    "setchatname": "Set this group’s title (Change info permission)",
    "setchatdescription": "Set description, or clear (Change info permission)",
    "setchatphoto": "Reply to a photo to set group photo (Change info permission)",
    "myinfo": "Your public Telegram identity card",
    "userinfo": "Public user card by reply, username or ID",
    "tiktok": "TikTok profile-link card; no live account lookup",
    "x": "X profile-link card; no live account lookup",
    "yt": "YouTube handle-link card; no live account lookup",
    "ig": "Instagram profile-link card; no live account lookup",
    "dwarn": "Warn and delete the replied message (admin)",
    "swarn": "Warn without public success confirmation (admin)",
    "resetallwarns": "Clear group active warnings with confirm; keep history (admin)",
    "rmwarn": "Clear latest active warning; retain history (admin)",
    "resetwarn": "Clear a member’s active warnings; retain history (admin)",
    "resetrules": "Clear this group’s rules; retain revisions (admin)",
    "gu": "Live card demo; /gu fail previews failure (group admin)",
    "broadcast": "Forward a reply to up to 50 known users/chats (owner, private)",
    "massban": "Ban up to 10 IDs in this group (owner, current rights)",
    "mychats": "Known chats with current admin membership (owner, private)",
    "bstats": "Database, instance lock and uptime (owner, private)",
    "sudo": "Manage scoped capabilities (owner)",
    "addsudo": "Grant an expiring capability (owner)",
    "delsudo": "Revoke a scoped capability (owner)",
    "sudolist": "List capability grants or history (owner)",
    "sudoperms": "Capability catalog or user grants (owner)",
    "autochat": "Opt-in private chat and group mention/reply AI mode",
    "ask": "Ask AI Agent; question goes to an external provider",
    "watchdog": "Runtime health; cleanup is Owner-only",
    "plugins": "Group controls or authorized plugin inspection",
    "plugin": "Enable or disable a plugin (owner)",
    "events": "Recent operational events (owner)",
    "errors": "Private error incident history (owner)",
    "db": "Database diagnostics; delegates get status only",
    "setlog": "Set the log channel (owner)",

    "log": "Show where events are logged (owner)",
}

#: Commands that only make sense inside a group.
GROUP_ONLY = frozenset(
    {
        "fullpromote", "adminbox", "afk", "userstats", "recentactivity", "admincount", "rights", "setchatname", "setchatdescription", "setchatphoto",
        "resetallwarns", "dwarn", "swarn", "rmwarn", "resetwarn", "resetrules",
        "lock", "unlock", "locks", "locktypes", "allowlist", "rmallowlist", "rmallowlistall", "warn", "warnings", "warns", "unwarn", "mute", "unmute", "kick", "ban",
        "tban", "tmute", "dban", "dmute", "dkick", "sban", "smute", "skick", "kickme", "unban", "purge", "spurge", "note", "approve", "unapprove", "approval", "approved", "addblocklist", "rmblocklist", "unblocklistall", "rmblocklistall", "blocklist", "blocklistmode", "blocklistdelete", "setblocklistreason", "resetblocklistreason", "cleanservice", "cleancommand", "keepcommand", "antispam", "modlog", "flood", "setflood", "setfloodtimer", "floodmode", "clearflood",
        "settings", "rules", "setrules", "pin", "unpin",
        "promote", "demote", "adminlist", "admincache", "anonadmin", "adminerror", "actiontopic", "setactiontopic", "newtopic", "renametopic", "closetopic", "reopentopic", "admins", "warntime", "warnmode", "warnlimit", "resetwarns", "lockdown",
        "play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "leave",
        "voicehealth", "q", "end", "resetplayer", "playnext", "loop", "shuffle", "clear", "clearqueue",
        "remove", "move", "jump", "replay", "seek", "fw", "bw", "seekback", "volume", "volumeup", "volumedown", "history",
        "saveplaylist", "playlist", "playlists", "deleteplaylist", "post", "verify",
        "addpremium", "delpremium", "premiumusers",
        "filter", "filters", "stopfilter",
        "setwelcome", "welcome", "goodbye",
    }
)


def sanitize(name: str) -> str | None:
    """Telegram rejects anything outside ``[a-z0-9_]``, so drop it rather than fail."""
    clean = (name or "").strip().lower().lstrip("/")
    return clean if VALID_NAME.match(clean) else None


# On overflow, retain useful entry points across features rather than only
# the first alphabetic commands. The complete active catalogue stays in Help.
MENU_ENTRY_POINTS = (
    'start', 'help', 'menu', 'ping', 'status', 'settings', 'plugins',
    'rules', 'report', 'verify', 'ban', 'mute', 'warn', 'warnings',
    'lock', 'locks', 'antispam', 'flood', 'filters', 'welcome', 'reports',
    'play', 'queue', 'stop', 'voicehealth', 'leech', 'encode', 'get', 'batch',
    'links', 'post', 'ask', 'clone', 'mybots', 'premium', 'plans',
    'myfeds', 'fedinfo', 'actiontopic', 'jobs', 'cancel', 'errors',
)


def curate(commands):
    if len(commands) <= MAX_COMMANDS:
        return commands
    by_name = {item.command: item for item in commands}
    priority = [by_name[name] for name in MENU_ENTRY_POINTS if name in by_name]
    chosen = {item.command for item in priority}
    return (priority + [item for item in commands if item.command not in chosen])[:MAX_COMMANDS]


def build_commands(names: Iterable[str], *, group: bool = False) -> list[BotCommand]:
    """BotCommand list for one scope, filtered and deduplicated."""
    seen: set[str] = set()
    commands: list[BotCommand] = []
    for raw in names:
        name = sanitize(raw)
        if name is None or name in seen:
            continue
        if (name in GROUP_ONLY) is not group:
            continue
        seen.add(name)
        description = DESCRIPTIONS.get(name, name.replace("_", " ").capitalize())
        commands.append(BotCommand(command=name, description=description[:MAX_DESCRIPTION]))
    return curate(commands)


async def publish(client, names: Iterable[str], *, command_scopes: dict[str, str] | None = None) -> tuple[int, int]:
    """Publish both scopes. Returns (private_count, group_count).

        Manifest scopes preserve shared commands in both chat types. Legacy
        callers without metadata retain the static split. Empty scopes clear old
        registrations. Failure is logged: handlers must keep answering commands.
        
    """
    names = list(names)
    if command_scopes is None:
        private = build_commands(names, group=False)
        group = build_commands(names, group=True)
    else:
        # A specific group scope replaces, rather than extends, the default.
        # Include all-scope controls such as /start and /uptime in both lists.
        def scoped(group):
            allowed = {"all", "group" if group else "private"}
            selected = [name for name in names if command_scopes.get(name) in allowed]
            # Build descriptions without the legacy static group filter.
            commands, seen = [], set()
            for raw in selected:
                name = sanitize(raw)
                if name is None or name in seen:
                    continue
                seen.add(name)
                commands.append(BotCommand(command=name, description=DESCRIPTIONS.get(name, name.replace("_", " ").capitalize())[:MAX_DESCRIPTION]))
            if len(commands) > MAX_COMMANDS:
                logger.warning("Telegram command scope exceeds its 100-command limit; help retains the full active list.")
            return curate(commands)
        private, group = scoped(False), scoped(True)
    done = {False: 0, True: 0}
    for is_group, (scope, commands) in zip((False, True), _scopes(private, group)):
        try:
            await asyncio.wait_for(client.set_bot_commands(commands, scope=scope), timeout=SYNC_TIMEOUT)
        except Exception:  # noqa: BLE001 - menu cosmetics must not stop the bot
            logger.exception("Could not publish the command menu")
            continue
        done[is_group] = len(commands)
    if done[False] or done[True]:
        logger.info(
            "Command menu published (%d private, %d group)", done[False], done[True]
        )
    return done[False], done[True]


def _scopes(private, group):
    from pyrogram.types import BotCommandScopeAllGroupChats, BotCommandScopeDefault

    return ((BotCommandScopeDefault(), private), (BotCommandScopeAllGroupChats(), group))


async def reset_menu_button(client) -> bool:
    """Remove the forced menu-button type; Telegram controls default visibility."""
    from pyrogram.types import MenuButtonDefault

    try:
        await asyncio.wait_for(client.set_chat_menu_button(menu_button=MenuButtonDefault()), timeout=SYNC_TIMEOUT)
        logger.info(
            "Custom menu button reset to Telegram default; Telegram may still show its Commands button."
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Could not reset the chat menu button")
        return False
