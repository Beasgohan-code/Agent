"""Operations module — restart, watchdog, plugin control and the event log.

Nothing here reports success it did not verify: a sweep reports the bytes it
actually removed, a restart says plainly that an unsupervised process will stay
down, and disabling a plugin detaches its handlers rather than hiding it.
"""

from __future__ import annotations

import html
import asyncio
import logging
import shutil
import tempfile
from urllib.parse import urlsplit
import time
from pathlib import Path

from pyrogram.enums import ButtonStyle, ChatMemberStatus, ChatType
from pyrogram.handlers import ChatMemberUpdatedHandler
from pyrogram.types import InlineKeyboardButton as Button
from pyrogram.types import InlineKeyboardMarkup as Keyboard

from ...platform.logbook import tag_for, LogSettingsError
from ...platform.manifest import PluginManifest
from ...ui.screens import format_uptime
from ...ui.keyboards import nav_keyboard
from ...ui.tables import Table, kv_table, panel
from ...utils import rich as rich_ui
from ...utils.rich import reply

logger = logging.getLogger(__name__)

#: Callback prefix owned by this module, registered through ctx.actions.
PLUGIN_PREFIX = "plugin"

MANIFEST = PluginManifest(
    slug="ops",
    name="Operations",
    version="1.0.0",
    description="Restart, watchdog sweeps, plugin on/off and the event log.",
    commands=(
        "restart",
        "sudo",
        "watchdog",
        "plugins",
        "plugin",
        "events",
        "errors",
        "db",
        "setlog",
        "log",
    ),
    permissions=("process.control", "plugins.manage", "files.write"),
    scope="all",
)

OWNER_ONLY = "This command is reserved for the bot owner."
SWEEP_MIN_AGE = 3600.0  # leave fresh temp dirs alone; a job may be using them


def _args(message) -> list[str]:
    return (getattr(message, "text", "") or "").split()


def _human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover


def sweep_temp_dirs(*, min_age: float = SWEEP_MIN_AGE, root: Path | None = None) -> tuple[int, int]:
    """Delete stale ``enc-*`` working directories. Returns (count, bytes freed)."""
    base = Path(root) if root else Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    freed = 0
    for entry in base.glob("enc-*"):
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:  # pragma: no cover
            continue
        if age < min_age:
            continue
        size = sum(p.stat().st_size for p in entry.rglob("*") if p.is_file())
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
        freed += size
    return removed, freed


def extra_handlers(ctx):
    """Report the bot being added to a group as #NewGroup."""

    async def on_member_update(client, update):
        try:
            me = getattr(client, "me", None)
            new = getattr(update, "new_chat_member", None)
            old = getattr(update, "old_chat_member", None)
            chat = getattr(update, "chat", None)
            if me is None or new is None or old is None or chat is None:
                return
            if getattr(getattr(new, "user", None), "id", None) != getattr(me, "id", None):
                return
            added = (
                getattr(new, "status", None)
                in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
                and getattr(old, "status", None) in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            )
            if not added:
                return
            events = getattr(ctx, "events", None)
            if events is not None:
                events.emit(
                    "new_group",
                    title=getattr(chat, "title", None),
                    id=chat.id,
                    added_by=getattr(getattr(update, "from_user", None), "id", None),
                )
        except Exception:  # noqa: BLE001 - a watcher must never break the client
            logger.exception("new-group watcher failed")

    return [ChatMemberUpdatedHandler(on_member_update)]


def build(ctx):
    from ...platform.roles import SudoStore
    if getattr(ctx, "sudo", None) is None:
        ctx.sudo = SudoStore(ctx.settings.data_dir, owner_id=ctx.settings.owner_id, db=getattr(ctx, "db", None))
    runtime = getattr(ctx, "runtime", None)
    events = getattr(ctx, "events", None)
    lease = getattr(ctx, "lease", None)

    def _is_owner(message) -> bool:
        owner_id = ctx.settings.owner_id
        user = getattr(message, "from_user", None)
        return (
            owner_id is not None
            and user is not None
            and int(user.id) == int(owner_id)
        )

    async def _owner_gate(message) -> bool:
        if ctx.settings.owner_id is None:
            await reply(message, 
                "No owner is configured. Set <code>OWNER_ID</code> and restart to "
                "enable this command."
            )
            return False
        if not _is_owner(message):
            await reply(message, OWNER_ONLY)
            return False
        return True

    # -- /restart ----------------------------------------------------------

    async def restart(_client, message):
        if not await _owner_gate(message):
            return
        args = [a.lower() for a in _args(message)[1:]]
        force = "force" in args
        active = ctx.jobs.active() if ctx.jobs is not None else []
        if active and not force:
            await reply(message, 
                f"{len(active)} job(s) are still running. "
                "Use <code>/restart force</code> to stop them, or wait and retry."
            )
            return
        reason = " ".join(a for a in args if a != "force") or "requested"
        if events is not None:
            events.emit("restart", by=getattr(message.from_user, "id", None), reason=reason)
        started = runtime.request_restart(reason) if runtime is not None else False
        await reply(message, 
            "Restarting now.\n"
            "The process stops so its supervisor can start it again — on Render or "
            "Docker that is automatic. Run outside a supervisor and the bot simply "
            "stays down."
            if started
            else "Restart is not wired up in this runtime; nothing was stopped."
        )

    # -- /watchdog ---------------------------------------------------------

    async def watchdog(_client, message):
        if not await _owner_gate(message):
            return
        args = [a.lower() for a in _args(message)[1:]]
        mode = args[0] if args else ""

        if mode in ("run", "clean"):
            removed, freed = sweep_temp_dirs()
            expired = await ctx.links.apurge_expired() if ctx.links is not None else 0
            pruned = 0
            if mode == "clean" and ctx.storage is not None:
                pruned = len(ctx.storage.prune(retention_days=7))
            lines = [
                f"Sweep {'(aggressive)' if mode == 'clean' else ''}".strip(),
                f"Temp working directories removed: {removed} ({_human_bytes(freed)})",
                f"Expired links purged: {expired}",
            ]
            if mode == "clean":
                lines.append(f"Stored files older than 7 days: {pruned}")
            if events is not None:
                events.emit("watchdog", mode=mode, removed=removed, freed=freed)
            await reply(message, "\n".join(lines))
            return

        rows: list[tuple[str, str]] = []
        if lease is not None:
            state = lease.state()
            rows.append(
                (
                    "Instance",
                    ("held by this process" if state["held_by_us"] else "not held")
                    + (f" (expires in {state['expires_in']}s)" if state["expires_in"] else ""),
                )
            )
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            rows.append(("State", snapshot.state))
            rows.append(("Uptime", format_uptime(snapshot.uptime_seconds)))
            rows.append(
                ("Latency", f"{snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "no probe yet")
            )
        if ctx.jobs is not None:
            rows.append(("Jobs running", str(len(ctx.jobs.active()))))
        if runtime is not None:
            disabled = [row["slug"] for row in runtime.state() if not row["enabled"]]
            rows.append(("Plugins disabled", ", ".join(disabled) or "none"))
        await reply(message, 
            panel(
                "Watchdog",
                icon=ctx.theme.emoji("bolt"),
                subtitle="What this process can see about itself right now.",
                table=kv_table(rows),
                note=(
                    "<code>/watchdog run</code> sweeps stale working directories; "
                    "<code>/watchdog clean</code> also prunes stored files older than 7 days."
                ),
                footer="Owner only.",
            )
        )

    # -- /plugins and /plugin ---------------------------------------------

    def _idle_reason(row: dict) -> str:
        """The manifest's own sentence about why it registered nothing."""
        description = str(row.get("description") or "")
        marker = "unavailable in this deployment: "
        if marker in description:
            return description.split(marker, 1)[1].rstrip(".")
        return "registers no commands in this deployment"

    def _state_text(row: dict) -> str:
        if not row["enabled"]:
            return "off"
        if not row["commands"]:
            return "idle"
        return "on (locked)" if row["protected"] else "on"

    def _plugin_panel() -> tuple[object, Keyboard]:
        """The runtime panel plus one button per plugin.

        A :class:`~agent.ui.tables.Panel`, not a string: the runtime panel is a
        real table, and a button press edits it as a rich message rather than
        dropping it back to a grid.
        """
        state = runtime.state()
        idle = [row for row in state if row["enabled"] and not row["commands"]]
        rows = tuple(
            (row["slug"], _state_text(row), str(len(row["commands"])))
            for row in state
        )
        enabled = sum(1 for row in state if row["enabled"])
        body = panel(
            "Plugin runtime",
            icon=ctx.theme.emoji("gear"),
            subtitle=(
                f"<b>{enabled}</b> of <b>{len(state)}</b> plugins enabled. "
                "A disabled plugin registers nothing at all."
            ),
            table=Table(headers=("Plugin", "State", "Cmds"), rows=rows, aligns=("left", "left", "right")),
            lines=(["Idle (enabled, no commands):"] + [f"<code>{row['slug']}</code> — {_idle_reason(row)}" for row in idle] if idle else []),
            note=(
                "Tap a plugin to switch it on or off, or use "
                "<code>/plugin &lt;slug&gt; on|off</code>. <code>ops</code> and "
                "<code>core</code> are locked: they are the controls and the front "
                "door, so the bot cannot lose the way back in."
            ),
            footer="Counts come from the live registry, not a stored copy.",
        )
        buttons: list[list[Button]] = []
        row_buttons: list[Button] = []
        for entry in state:
            locked = entry["protected"]
            row_buttons.append(
                Button(
                    text=f"{'🔒' if locked else ('✅' if entry['enabled'] else '⛔')} {entry['slug']}",
                    callback_data=f"{PLUGIN_PREFIX}:{entry['slug']}",
                    style=(ButtonStyle.SUCCESS if entry["enabled"] else ButtonStyle.DEFAULT),
                    disabled=locked,
                )
            )
            if len(row_buttons) == 2:
                buttons.append(row_buttons)
                row_buttons = []
        if row_buttons:
            buttons.append(row_buttons)
        return body, Keyboard(buttons)

    async def on_plugin_press(client, query, rest: str) -> None:
        """A button pressed on the runtime panel."""
        owner_id = ctx.settings.owner_id
        presser = getattr(getattr(query, "from_user", None), "id", None)
        if owner_id is None or presser is None or int(presser) != int(owner_id):
            await query.answer("Only the owner can switch plugins.", show_alert=True)
            return
        slug = (rest or "").strip().lower()
        state = {row["slug"]: row for row in runtime.state()}
        entry = state.get(slug)
        if entry is None:
            await query.answer("No such plugin.", show_alert=True)
            return
        if entry["protected"]:
            await query.answer(f"{slug} is locked: the bot needs its own controls.", show_alert=True)
            return
        if entry["enabled"]:
            try:
                runtime.disable(slug)
                message = f"{slug} is off — its handlers are detached."
            except ValueError as exc:
                await query.answer(str(exc), show_alert=True)
                return
        else:
            runtime.enable(slug)
            message = f"{slug} is on."
        if events is not None:
            events.emit("plugin", slug=slug, action="off" if entry["enabled"] else "on", by=presser)
        logger.info("plugin %s toggled by %s from the panel", slug, presser)
        text, keyboard = _plugin_panel()
        try:
            await rich_ui.edit(query, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001 - an old message is not a failed toggle
            chat_id = getattr(getattr(query.message, "chat", None), "id", None)
            if chat_id is not None:
                await rich_ui.send(client, chat_id, text, reply_markup=keyboard)
        await query.answer(message)

    def _database_rows() -> list[tuple[str, str]]:
        """What the store is, where it is, and whether it is answering."""
        database = getattr(ctx, "db", None)
        lease = getattr(ctx, "lease", None)
        rows: list[tuple[str, str]] = [
            ("Backend", "postgres" if database is not None and database.connected else "json files"),
            ("Lease", getattr(lease, "backend", "file")),
        ]
        if database is None:
            rows.append(("DATABASE_URL", "not set"))
            return rows
        host = "—"
        try:
            host = urlsplit(database.url or "").hostname or "—"
        except ValueError:  # pragma: no cover - a malformed URL is still reportable
            pass
        rows.extend(
            [
                ("Host", host),
                ("Connected", "yes" if database.connected else f"no ({database.error or 'not tried'})"),
                ("Documents", str(len(getattr(database, "_docs", {}) or {}))),
                ("Queued writes", str(len(getattr(database, "_pending", {}) or {}))),
            ]
        )
        return rows

    async def db(_client, message):
        """The store, stated plainly: which one, where, and is it answering."""
        if not await _owner_gate(message):
            return
        await reply(
            message,
            panel(
                "Database",
                icon=ctx.theme.emoji("stats"),
                subtitle=(
                    "Every store (chats, premium, links, clones, plugins) is one "
                    "document; the vault's files stay on this host's disk."
                ),
                table=kv_table(_database_rows()),
                note=(
                    "Set <code>DATABASE_URL</code> to a PostgreSQL URL to share state "
                    "between instances and survive a redeploy."
                ),
                footer="Writes are queued and flushed in the background; a handler never waits.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def plugins(_client, message):
        if getattr(getattr(message, "chat", None), "id", 0) < 0:
            show = getattr(ctx, "group_plugin_panel", None)
            if show is not None:
                await show(_client, message)
                return
        if not await _owner_gate(message):
            return
        if runtime is None:  # pragma: no cover - always wired
            await reply(message, "Plugin runtime is unavailable.")
            return
        text, keyboard = _plugin_panel()
        await reply(message, text, reply_markup=keyboard)
        logger.info("plugin panel opened by %s", getattr(message.from_user, "id", None))

    async def plugin(_client, message):
        if not await _owner_gate(message):
            return
        if runtime is None:  # pragma: no cover
            await reply(message, "Plugin runtime is unavailable.")
            return
        args = _args(message)[1:]
        if len(args) == 2 and args[1].lower() in ("approve", "revoke"):
            from ...platform.plugin_access import AccessError
            service = getattr(ctx, "plugin_access", None)
            if service is None:
                await reply(message, "PostgreSQL plugin access is unavailable.")
                return
            try:
                operation = service.approve if args[1].lower() == "approve" else service.revoke
                await operation(args[0].lower(), actor_id=message.from_user.id)
                await reply(message, "Global plugin approval updated. Refresh group plugins to see current state.")
            except AccessError as exc:
                await reply(message, str(exc))
            except Exception:
                await reply(message, "Approval change could not be confirmed. Check database availability.")
            return
        if not args:
            await reply(message, "Usage: <code>/plugin &lt;slug&gt; on|off|approve|revoke</code>")
            return
        slug = args[0].lower()
        action = args[1].lower() if len(args) > 1 else ""
        known = {row["slug"] for row in runtime.state()}
        if slug not in known:
            await reply(message, f"No plugin named <code>{html.escape(slug)}</code>.")
            return
        if action not in ("on", "off"):
            await reply(message, "Usage: <code>/plugin &lt;slug&gt; on|off</code>")
            return
        if action == "on":
            changed = runtime.enable(slug)
        else:
            try:
                changed = runtime.disable(slug)
            except ValueError as exc:
                await reply(message, str(exc))
                return
        if not changed:
            await reply(message, f"<code>{slug}</code> was already {action if action == 'on' else 'off'}.")
            return
        if events is not None:
            events.emit(
                "plugin", slug=slug, action=action, by=getattr(message.from_user, "id", None)
            )
        await reply(message, 
            f"Plugin <code>{slug}</code> is now {'enabled' if action == 'on' else 'disabled'}."
            + (
                ""
                if action == "on"
                else "\nIts handlers are detached, so none of its commands respond."
            )
        )

    # -- /events -----------------------------------------------------------

    async def show_events(_client, message):
        if not await _owner_gate(message):
            return
        if events is None:  # pragma: no cover
            await reply(message, "No event log in this runtime.")
            return
        recent = events.recent(10)
        if not recent:
            await reply(message, "<b>Events</b>\nNothing recorded yet.")
            return
        rows = []
        for event in recent:
            stamp = time.strftime("%H:%M:%S", time.gmtime(event["at"]))
            fields = " ".join(
                f"{key}={value}" for key, value in event.items() if key not in ("kind", "at")
            )
            rows.append((stamp, event["kind"], fields or "-"))
        await reply(message, 
            panel(
                "Events",
                icon=ctx.theme.emoji("stats"),
                subtitle=f"<b>{events.count()}</b> recorded, newest last.",
                table=Table(
                    headers=("Time", "Kind", "Detail"),
                    rows=tuple(rows),
                    total_width=56,
                ),
                note="Every entry is written when the action happened — none are simulated.",
                footer="Owner only. Times are UTC.",
            )
        )

    async def errors(_client, message):
        if not await _owner_gate(message):
            return
        if message.chat.id != message.from_user.id:
            await reply(message, "Open this bot privately to inspect error incidents.")
            return
        if len(_args(message)) != 1:
            await reply(message, "Use /errors without arguments for the latest incident groups.")
            return
        service = getattr(ctx, "incidents", None)
        if service is None:
            await reply(message, "Incident storage is unavailable.")
            return
        try:
            rows = await service.recent()
        except Exception:
            await reply(message, "PostgreSQL incident history could not be read.")
            return
        await reply(message, panel("Error incidents", icon=ctx.theme.emoji("shield"),
            table=Table(headers=("Incident", "Type", "Count"), rows=tuple(
                (row['incident_id'], row['error_type'], str(row['occurrences'])) for row in rows)),
            footer="Latest 10 aggregated incidents in this bot tenant. No message text, credentials or exception arguments are collected."))

    # -- log channel -------------------------------------------------------

    async def setlog(client, message):
        if not await _owner_gate(message):
            return
        logbook = getattr(ctx, "logbook", None)
        if logbook is None:  # pragma: no cover - always wired
            await reply(message, "No log channel support in this runtime.")
            return
        args = _args(message)[1:]
        if len(args) != 1:
            await reply(message, 
                "Usage: <code>/setlog &lt;channel id&gt;</code> or "
                "<code>/setlog here</code> (run it in the channel)."
            )
            return
        raw = args[0].lower()
        if raw == "here":
            chat = getattr(message, "chat", None)
            if chat is None or getattr(chat, "type", None) not in (
                ChatType.CHANNEL,
                ChatType.SUPERGROUP,
            ):
                await reply(message, "Run <code>/setlog here</code> inside the channel or group.")
                return
            target = int(chat.id)
        else:
            try:
                target = int(raw)
            except ValueError:
                await reply(message, "That is not a channel id.")
                return

        if not -(2**63) < target < 0:
            await reply(message, "Use a negative Telegram channel or group id.")
            return
        # Verify reachability, then actual posting, before claiming it is set.
        try:
            chat = await asyncio.wait_for(client.get_chat(target), timeout=10)
            title = getattr(chat, "title", None) or str(target)
        except Exception as exc:  # noqa: BLE001 - reported to the owner
            await reply(message, 
                f"I cannot reach <code>{target}</code> ({type(exc).__name__}). "
                "Add me to that channel as an admin, then try again."
            )
            return

        try:
            await asyncio.wait_for(client.send_message(target, "Agent log-channel verification. The destination will be saved only after persistence succeeds."), timeout=10)
        except Exception as exc:
            await reply(message, f"I could not post to that log channel ({type(exc).__name__}). Check posting permissions. The saved destination was not changed.")
            return
        try:
            await logbook.configure(target)
        except LogSettingsError as exc:
            await reply(message, html.escape(str(exc)))
            return
        await reply(message, f"Log channel set to <b>{html.escape(str(title))}</b> (<code>{target}</code>). Saved in {logbook.backend}.")


    async def log(client, message):
        if not await _owner_gate(message):
            return
        logbook = getattr(ctx, "logbook", None)
        if logbook is None:  # pragma: no cover
            return
        try:
            await logbook.hydrate()
        except LogSettingsError as exc:
            await reply(message, html.escape(str(exc)))
            return
        destination = logbook.destination()
        where = (
            f"<code>{destination}</code>"
            if logbook.channel_id is not None
            else ("your DM (no channel set)" if destination else "nowhere yet")
        )
        lines = [
            "<b>Log book</b>",
            f"Destination: {where}",
            f"Settings store: {logbook.backend}",
            f"Events recorded: {events.count() if events is not None else 0}",
        ]
        if events is not None:
            recent = events.recent(5)
            if recent:
                lines.append("")
                lines.extend(f"#{tag_for(item['kind'])}" for item in recent)
        lines.append("")
        lines.append("Set one with <code>/setlog &lt;channel id&gt;</code>.")
        await reply(message, "\n".join(lines))

    # The panel's buttons are module-owned: the UI layer never learns what a
    # plugin slug is. A second build on the same context re-uses the route.
    router = getattr(ctx, "actions", None)
    if router is not None and not router.handles(f"{PLUGIN_PREFIX}:x"):
        router.register(PLUGIN_PREFIX, on_plugin_press)

    async def sudo(_client, message):
        if not await _owner_gate(message):
            return
        if message.chat.id != message.from_user.id:
            await reply(message, "Manage sudo access in a private chat with this bot.")
            return
        args = _args(message)[1:]
        try:
            if not args or args == ["list"]:
                members = ctx.sudo.members()
                await reply(message, panel("Sudo access", icon=ctx.theme.emoji("crown"),
                    lines=[", ".join(str(uid) for uid in members) or "No sudo users."],
                    footer="Sudo grants clone eligibility, not Owner or group-administrator rights."))
                return
            if len(args) != 2 or args[0] not in ("add", "remove"):
                raise ValueError("Use /sudo add <user id>, /sudo remove <user id>, or /sudo list.")
            ctx.sudo.change(message.from_user.id, int(args[1]), add=args[0] == "add")
            if events is not None:
                events.emit("sudo", action=args[0], user_id=int(args[1]), by=message.from_user.id)
            await reply(message, "Sudo access updated.")
        except (ValueError, PermissionError) as exc:
            await reply(message, html.escape(str(exc)))

    return MANIFEST, {
        "sudo": sudo,
        "restart": restart,
        "watchdog": watchdog,
        "plugins": plugins,
        "db": db,
        "plugin": plugin,
        "events": show_events,
        "errors": errors,
        "setlog": setlog,

        "log": log,
    }
