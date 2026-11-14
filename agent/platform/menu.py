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
import re
from typing import Iterable

from pyrogram.types import BotCommand

logger = logging.getLogger(__name__)

#: Telegram: 1-32 chars, lowercase letters, digits and underscores only.
VALID_NAME = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_COMMANDS = 100
MAX_DESCRIPTION = 256

#: One line per command, kept short — this is menu text, not documentation.
DESCRIPTIONS: dict[str, str] = {
    # core
    "start": "Open the main menu",
    "help": "Full command reference",
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
    "fsave": "Save a replied file to your vault",
    "get": "Re-send a file from your vault",
    "files": "List your vault",
    "batch": "Save a run of files into your vault",
    "check": "Everything about one vault entry",
    "del": "Delete one vault entry",
    "storestats": "Vault usage statistics",
    "storequota": "Vault quota and what is left",
    # leech
    "leech": "Download an http(s) link and send it here",
    "mirror": "Download a link and keep it in your vault",
    "tasklist": "Your download tasks",
    "taskstatus": "Detail of one task",
    "leechstats": "Your task counts",
    "taskbackend": "Which transfer backends exist here",
    # music (voice chat)
    "play": "Stream audio into the voice chat",
    "pause": "Pause playback",
    "resume": "Resume playback",
    "skip": "Play the next track",
    "stop": "Stop and clear the queue",
    "queue": "Show the playback queue",
    "nowplaying": "What this group is playing",
    "leave": "Leave the voice chat",
    # reports / posts / security
    "report": "Report a message to the moderators",
    "reports": "Work the report queue",
    "appeal": "Appeal a moderation action",
    "post": "Publish a formatted post",
    "postpreview": "Preview a post before publishing",
    "posttemplate": "Set this group's post template",
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
    "toaudio": "Extract the audio track as MP3",
    "screens": "Contact sheet of frames from a video",
    "encinfo": "Probe a replied video",
    "encpreset": "List encoding presets",
    "enccancel": "Cancel your encoding jobs",
    # linkshare
    "genlink": "Create a signed link for a file",
    "links": "List your links",
    "revoke": "Revoke one of your links",
    # renamer
    "autorename": "Set the filename template",
    "rename": "Rename a replied file",
    "testrename": "Preview a rename",
    "clean": "Tidy a filename",
    "setthumb": "Use a replied image as this chat's thumbnail",
    "delthumb": "Stop attaching a thumbnail",
    "viewthumb": "Show the thumbnail this chat uses",
    "setcaption": "Set the caption files are sent with",
    "delcaption": "Stop adding a caption",
    "viewcaption": "Show the caption with an example",
    # ops (owner)
    "restart": "Restart the process (owner)",
    "watchdog": "Health and cleanup sweeps (owner)",
    "plugins": "List plugins and their state (owner)",
    "plugin": "Enable or disable a plugin (owner)",
    "events": "Recent operational events (owner)",
    "setlog": "Set the log channel (owner)",
    "unsetlog": "Clear the log channel (owner)",
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
        "post", "postpreview", "posttemplate", "verify",
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


async def publish(client, names: Iterable[str]) -> tuple[int, int]:
    """Publish both scopes. Returns (private_count, group_count).

        Failure is logged, never raised: a bot that cannot set its menu must still
        answer commands.
        
    """
    names = list(names)
    private = build_commands(names, group=False)
    group = build_commands(names, group=True)
    done = {False: 0, True: 0}
    for is_group, (scope, commands) in zip((False, True), _scopes(private, group)):
        if not commands:
            continue
        try:
            await client.set_bot_commands(commands, scope=scope)
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
    """Point the chat menu button at the command list instead of a web app."""
    from pyrogram.types import MenuButtonCommands

    try:
        await client.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info(
            "Menu button reset to the command list (the Bot API has no option to "
            "hide it entirely)."
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Could not reset the chat menu button")
        return False
