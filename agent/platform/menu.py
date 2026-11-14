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
    "cancel": "Stop your running jobs",
    "owner": "Owner control panel",
    "ping": "Health and latency of this instance",
    # clone
    "clone": "Clone this bot onto another token",
    "mybots": "Your clones and their controls",
    "delclone": "Delete one of your clones",
    "clonestats": "Clone counts (owner)",
    # moderation
    "warn": "Warn a member",
    "warnings": "List a member's warnings",
    "warns": "Alias of /warnings",
    "unwarn": "Clear one warning",
    "mute": "Temporarily restrict a member",
    "unmute": "Restore a member's permissions",
    "kick": "Remove a member (they may return)",
    "ban": "Ban a member",
    "unban": "Lift a ban",
    "purge": "Delete the last N messages",
    "note": "Attach a private note to a member",
    "trust": "Toggle a member's trusted flag",
    "antispam": "Anti-spam policy for this group",
    "modlog": "Recent moderation actions",
    # group management
    "settings": "This group's live settings panel",
    "rules": "Show this group's rules",
    "setrules": "Publish this group's rules",
    "pin": "Pin the replied message",
    "unpin": "Unpin a message, or all of them",
    "admins": "List this group's administrators",
    "warnlimit": "Warnings needed to trigger an action",
    "resetwarns": "Clear all warnings for a member",
    "lockdown": "Restrict the group to administrators",
    # filestore

    "get": "Re-send a file from your vault",
    "files": "Browse your vault: /files [page]",
    "batch": "Save a run of files into your vault",
    "check": "Everything about one vault entry",
    "del": "Delete one vault entry",


    # leech
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
    "volume": "View or set voice-chat volume",
    "volumeup": "Increase voice-chat volume by 20 percent",
    "volumedown": "Decrease voice-chat volume by 20 percent",
    "history": "Recent acknowledged music titles this session",
    "saveplaylist": "Save your group's queue as a named playlist",

    "playlist": "Append your saved playlist to the current queue",
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
    "repo": "Where this bot's source lives",
    # encoder
    "encode": "Encode a replied video",
    "compress": "Make a replied video smaller (fast preset)",
    "sample": "Cut a short clip from a replied video",
    "toaudio": "Extract audio as MP3, M4A or FLAC",
    "screens": "Create a 4, 9 or 16-frame contact sheet",
    "mediainfo": "Probe a replied video",

    # linkshare
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
    # ops (owner)
    "restart": "Restart the process (owner)",
    "sudo": "Manage delegated clone access (owner)",
    "ask": "Ask AI Agent; question goes to an external provider",
    "watchdog": "Health and cleanup sweeps (owner)",
    "plugins": "List plugins and their state (owner)",
    "plugin": "Enable or disable a plugin (owner)",
    "events": "Recent operational events (owner)",
    "errors": "Private error incident history (owner)",
    "db": "The state store: backend, host, health (owner)",
    "setlog": "Set the log channel (owner)",

    "log": "Show where events are logged (owner)",
}

#: Commands that only make sense inside a group.
GROUP_ONLY = frozenset(
    {
        "warn", "warnings", "warns", "unwarn", "mute", "unmute", "kick", "ban",
        "unban", "purge", "note", "trust", "antispam", "modlog",
        "settings", "rules", "setrules", "pin", "unpin",
        "admins", "warnlimit", "resetwarns", "lockdown",
        "play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "leave",
        "voicehealth", "q", "end", "resetplayer", "playnext", "loop", "shuffle", "clear", "clearqueue",
        "remove", "move", "jump", "replay", "seek", "volume", "volumeup", "volumedown", "history",
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
    return commands[:MAX_COMMANDS]


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
            return commands[:MAX_COMMANDS]
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
