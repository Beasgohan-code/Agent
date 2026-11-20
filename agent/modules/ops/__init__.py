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

from pyrogram.errors import MessageNotModified
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
    group_compatible=True,
    clone_compatible=False,
    slug="ops",
    name="Operations",
    version="1.0.0",
    description="Restart, watchdog sweeps, plugin on/off and the event log.",
    commands=(
        "restart",
        "bstats",
        "mychats",
        "massban",
        "broadcast",
        "sudo",
        "addsudo", "delsudo", "sudolist", "sudoperms",
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
    from ...platform.sudo_access import SudoAccess
    from .sudo_commands import build as sudo_commands
    capabilities = SudoAccess(getattr(ctx, "db", None), owner_id=ctx.settings.owner_id)
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

    async def _delegated(message, capability):
        uid = getattr(getattr(message, "from_user", None), "id", None)
        chat_id = getattr(getattr(message, "chat", None), "id", 0)
        return await capabilities.allowed(uid, capability, chat_id if type(chat_id) is int and chat_id < 0 else 0)

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
        args = [a.lower() for a in _args(message)[1:]]
        if not _is_owner(message):
            if not args and await _delegated(message, "health.read"):
                rows = [("State", "Health monitor unavailable")]
                if ctx.monitor is not None:
                    snapshot = ctx.monitor.snapshot()
                    rows = [("State", snapshot.state), ("Process uptime", format_uptime(snapshot.uptime_seconds))]
                await reply(message, panel("Runtime health", table=kv_table(rows),
                    note="Read-only process status. Cleanup and restart remain Owner-only."))
            else:
                await _owner_gate(message)
            return
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
        from ...platform.policy import GROUP_CORE
        raw = runtime.state()
        management = [row for row in raw if row["slug"] in GROUP_CORE]
        state = [row for row in raw if row["slug"] not in {*GROUP_CORE, "ops", "core"}]
        if management:
            state.insert(0, {
                "slug": "group", "name": "Group Management", "enabled": all(row["enabled"] for row in management),
                "commands": list({cmd for row in management for cmd in row["commands"]}),
                "protected": True,
            })
        rows = tuple((row.get("name") or row["slug"], _state_text(row)) for row in state)
        body = panel(
            "Plugin runtime", icon=ctx.theme.emoji("gear"),
            subtitle="One Group Management suite · optional tools below",
            table=Table(headers=("Plugin", "State"), rows=rows),
            lines=["Group Management includes moderation, welcome messages, anti-spam, filters, reports and verification."] + [
                f"{html.escape(row.get('name') or row['slug'])}: {html.escape(_idle_reason(row))}"
                for row in state if row["enabled"] and not row["commands"]
            ],
            note="Group Management stays on and uses no optional slots. Group admins configure its individual rules through /settings.",
            footer="Optional switches control this bot’s runtime. Group activation still requires approval and an available slot.",
        )
        buttons: list[list[Button]] = []
        row_buttons: list[Button] = []
        for entry in state:
            locked = entry["protected"]
            row_buttons.append(
                ctx.theme.button(
                    text=f"{entry.get('name') or entry['slug']}", icon='lock' if locked else 'gear',
                    callback_data=f"{PLUGIN_PREFIX}:info:{entry['slug']}",
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

    def _plugin_workspace(entry):
        slug = entry['slug']
        commands = entry['commands']
        body = panel(entry.get('name') or slug, icon=ctx.theme.emoji('gear'),
            subtitle='Plugin workspace · this bot runtime',
            table=kv_table([
                ('Runtime', _state_text(entry)),
                ('Scope', str(entry.get('scope', 'unknown'))),
                ('Registered commands', str(len(commands))),
                ('Executable handlers', str(entry.get('tracked_handlers', 0))),
                ('Control', 'protected' if entry['protected'] else 'Owner managed'),
            ]),
            lines=[html.escape(str(entry.get('description') or 'No description supplied.')),
                   'Commands: ' + (' · '.join('/' + html.escape(cmd) for cmd in commands[:16]) or 'none registered'),
                   f'Group setup: <code>/plugin {html.escape(slug)} approve</code>, then a group admin activates it in that group’s /plugins.'],
            note='Runtime on does not grant group approval or prove provider connectivity. Turning it off detaches handlers; it does not revoke approval or free group slots.',
            footer='Refresh is read-only. Use /help for command usage; credentials are never displayed here.')
        buttons = []
        if not entry['protected'] and entry.get('tracked_handlers', 0):
            buttons.append([ctx.theme.button('Disable runtime…' if entry['enabled'] else 'Enable runtime',
                icon='ban' if entry['enabled'] else 'bolt', style=ButtonStyle.DANGER if entry['enabled'] else ButtonStyle.PRIMARY,
                callback_data=f'{PLUGIN_PREFIX}:ask:{slug}' if entry['enabled'] else f'{PLUGIN_PREFIX}:on:{slug}')])
        buttons += [[ctx.theme.button('Refresh', icon='stats', style=ButtonStyle.DEFAULT, callback_data=f'{PLUGIN_PREFIX}:info:{slug}')],
                    [ctx.theme.button('‹ Plugin runtime', icon='back', style=ButtonStyle.DEFAULT, callback_data=f'{PLUGIN_PREFIX}:home')]]
        return body, Keyboard(buttons)

    async def _edit_plugin(query, body, keyboard):
        try:
            await rich_ui.edit(query, body, reply_markup=keyboard)
        except MessageNotModified:
            pass

    async def on_plugin_press(client, query, rest: str) -> None:
        """A button pressed on the runtime panel."""
        owner_id = ctx.settings.owner_id
        presser = getattr(getattr(query, "from_user", None), "id", None)
        if owner_id is None or presser is None or int(presser) != int(owner_id):
            await query.answer("Only the owner can switch plugins.", show_alert=True)
            return
        parts = (rest or '').strip().lower().split(':')
        if parts == ['home']:
            body, keyboard = _plugin_panel()
            await _edit_plugin(query, body, keyboard)
            await query.answer()
            return
        # Old saved bare-slug buttons now browse safely instead of toggling.
        action, slug = ('info', parts[0]) if len(parts) == 1 else (parts if len(parts) == 2 else ('invalid', ''))
        state = {row['slug']: row for row in runtime.state()}
        entry = state.get(slug)
        if entry is None or action not in ('info', 'ask', 'on', 'off'):
            await query.answer('No such plugin or control.', show_alert=True)
            return
        if action == 'info' and not entry['protected']:
            body, keyboard = _plugin_workspace(entry)
            await _edit_plugin(query, body, keyboard)
            await query.answer()
            return
        if entry["protected"]:
            await query.answer(f"{slug} is locked: the bot needs its own controls.", show_alert=True)
            return
        if action == 'ask':
            await _edit_plugin(query, panel('Disable runtime?', lines=[
                f'Detach <b>{html.escape(slug)}</b> handlers for this bot? Its commands stop responding in every chat.',
                'This does not revoke Owner approval or release group slots. Running external jobs are not guaranteed to stop.'],
                note='Use the group plugin panel to disable only one group.'), Keyboard([
                    [ctx.theme.button('Confirm disable runtime', icon='ban', style=ButtonStyle.DANGER, callback_data=f'{PLUGIN_PREFIX}:off:{slug}')],
                    [ctx.theme.button('Cancel', icon='back', style=ButtonStyle.DEFAULT, callback_data=f'{PLUGIN_PREFIX}:info:{slug}')]]))
            await query.answer()
            return
        try:
            changed = runtime.disable(slug) if action == 'off' else runtime.enable(slug)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        except RuntimeError:
            await query.answer('Runtime change could not be confirmed. Check /errors and refresh before retrying; no success is claimed.', show_alert=True)
            return
        message = (f'{slug} is off — its handlers are detached.' if action == 'off' else
                   f'{slug} runtime is on. Next: /plugin {slug} approve, then group-admin activation in /plugins.')
        if not changed:
            current = {row['slug']: row for row in runtime.state()}[slug]
            body, keyboard = _plugin_workspace(current)
            await _edit_plugin(query, body, keyboard)
            if action == 'off' and not current['enabled']:
                reason = f'{slug} is already off.'
            elif not current.get('tracked_handlers'):
                reason = f'{slug} cannot start: {_idle_reason(current)}. Configure this bot and restart with authorization.'
            else:
                reason = f'{slug} is already on. Group use still needs Owner approval and group-admin activation.'
            await query.answer(reason[:195], show_alert=not bool(current.get('tracked_handlers')))
            return
        if events is not None:
            events.emit("plugin", slug=slug, action=action, by=presser)
        logger.info("plugin %s toggled by %s from the panel", slug, presser)
        text, keyboard = _plugin_workspace({row["slug"]: row for row in runtime.state()}[slug])
        try:
            await _edit_plugin(query, text, keyboard)
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
            ("Storage", "Connected" if database is not None and database.connected else "Unavailable"),
            ("Lease", "Shared storage" if getattr(lease, "backend", "file")=="postgres" else "Local compatibility"),
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

    bulk_lock = asyncio.Lock()
    bulk_seen = set()

    async def massban(client, message):
        # Serialize admissions in this runtime and reject duplicate update IDs.
        # This is not durable exactly-once delivery across process restarts.
        if not _is_owner(message):
            await reply(message, OWNER_ONLY)
            return
        key = (getattr(getattr(message, 'chat', None), 'id', None), getattr(message, 'id', None))
        if bulk_lock.locked() or (key[1] is not None and key in bulk_seen):
            await reply(message, 'A bulk action is active or this request was already admitted. No new bans attempted.')
            return
        async with bulk_lock:
            if key[1] is not None:
                if len(bulk_seen) >= 1000:
                    await reply(message, 'Bulk admission window full. No new bans attempted; use individual moderation commands.')
                    return
                bulk_seen.add(key)
            from .massban import massban as execute
            await execute(ctx, client, message)

    async def broadcast(client, message):
        from .broadcast import broadcast as execute
        await execute(ctx, client, message)

    async def mychats(client, message):
        if not _is_owner(message):
            await reply(message, OWNER_ONLY)
            return
        owner = ctx.settings.owner_id
        if getattr(getattr(message, 'chat', None), 'id', None) != owner:
            await reply(message, 'Open a private chat with this bot to list known chats.')
            return
        parts = _args(message)
        if len(parts) > 2 or (len(parts) == 2 and (not parts[1].isascii() or not parts[1].isdigit()
                or len(parts[1]) > 6 or int(parts[1]) < 1)):
            await reply(message, 'Usage: <code>/mychats [page]</code> — positive page number.')
            return
        page = int(parts[1]) if len(parts) == 2 else 1
        store = getattr(ctx, 'chats', None)
        if store is None:
            await reply(message, 'Known-chat index unavailable.')
            return
        ids, total = store.known_group_page(page)
        pages = max(1, (total + 9) // 10)
        if page > pages:
            await reply(message, f'No such page. Available pages: 1–{pages}.')
            return
        rows, unconfirmed = [], 0
        for cid in ids:
            if ctx.settings.owner_id != owner:
                await reply(message, 'Owner configuration changed. Start again; no chat list shown.')
                return
            try:
                member = await asyncio.wait_for(client.get_chat_member(cid, owner), timeout=3)
                if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                    continue
                chat = await asyncio.wait_for(client.get_chat(cid), timeout=3)
                if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
                    continue
                rows.append((str(getattr(chat, 'title', None) or 'Untitled')[:80], str(cid)))
            except Exception as error:
                unconfirmed += 1
                logger.warning('#Errors Known-chat check unconfirmed (%s)', type(error).__name__)
        if ctx.settings.owner_id != owner:
            await reply(message, 'Owner configuration changed. Start again; no chat list shown.')
            return
        await reply(message, panel('Your known admin chats', icon=ctx.theme.emoji('shield'),
            table=Table(headers=('Chat', 'ID'), rows=tuple(rows)) if rows else None,
            lines=[] if rows else ['No current admin memberships confirmed on this page.'],
            note=f'Page {page}/{pages} · Checked {len(ids)} known chats · {unconfirmed} unconfirmed. '
                 'Only this bot’s cached chat index is searched, not every chat you administer. '
                 'Pages cover known chats, including non-admin and unavailable entries. Use /mychats followed by a page number.',
            ), reply_markup=nav_keyboard())

    async def bstats(_client, message):
        if not _is_owner(message):
            await reply(message, OWNER_ONLY)
            return
        if getattr(getattr(message, 'chat', None), 'id', None) != ctx.settings.owner_id:
            await reply(message, 'Open a private chat with this bot to view Owner diagnostics.')
            return
        if len(_args(message)) != 1:
            await reply(message, 'Usage: <code>/bstats</code>')
            return
        database = getattr(ctx, 'db', None)
        lease = getattr(ctx, 'lease', None)
        monitor = getattr(ctx, 'monitor', None)
        jobs = getattr(ctx, 'jobs', None)
        rows = [
            ('Database', 'Connected' if database is not None and database.connected else 'Unavailable'),
            ('Queued writes', str(len(getattr(database, '_pending', {}) or {}))),
            ('Instance lock', ('held' if lease.held else 'not held') if lease is not None else 'Unavailable'),
            ('Lock storage', ('Shared storage' if lease.backend=='postgres' else 'Local compatibility') if lease is not None else 'Unavailable'),
            ('Lock degraded', ('yes' if lease.degraded else 'no') if lease is not None else 'Unavailable'),
            ('Uptime', format_uptime(monitor.snapshot().uptime_seconds) if monitor is not None else 'Unavailable'),
            ('Active jobs', str(len(jobs.active())) if jobs is not None else 'Unavailable'),
        ]
        await reply(message, panel('Bot statistics', icon=ctx.theme.emoji('stats'), table=kv_table(rows),
                    note='Local runtime snapshot; connection state is not a fresh database health probe. Instance lock is this process lease, not a count of database locks.'),
                    reply_markup=nav_keyboard())

    async def db(_client, message):
        """Owner diagnostics; delegates see only a bounded, sanitized status."""
        if not _is_owner(message):
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            chat_id = getattr(getattr(message, "chat", None), "id", 0)
            if not await capabilities.allowed(user_id, "diagnostics.read", chat_id if chat_id < 0 else 0):
                await reply(message, OWNER_ONLY)
                return
            database = getattr(ctx, "db", None)
            await reply(message, "Database connection: " + ("available" if database is not None and database.connected else "unavailable") + ". No credentials or private metadata are included.")
            return
        await reply(
            message,
            panel(
                "Database",
                icon=ctx.theme.emoji("stats"),
                subtitle=(
                    "Stored state includes relational records and scoped "
                    "documents; durable media requires configured remote archives."
                ),
                table=kv_table(_database_rows()),
                note=(
                    "Configure <code>DATABASE_URL</code> to share state "
                    "between instances and survive a redeploy."
                ),
                footer="Critical transactional writes are awaited; legacy settings still use queued writes.",
            ),
            reply_markup=nav_keyboard(),
        )

    async def plugins(_client, message):
        if not _is_owner(message) and await _delegated(message, "plugins.inspect"):
            if runtime is None:
                await reply(message, "Plugin inventory is unavailable.")
                return
            from ...platform.policy import GROUP_CORE
            state = runtime.state()
            management = [entry for entry in state if entry["slug"] in GROUP_CORE]
            rows = [("Group Management", "On" if all(entry["enabled"] for entry in management) else "Degraded")] if management else []
            rows += [(entry.get("name") or entry["slug"], "Off" if not entry["enabled"] else "On" if entry["commands"] else "Idle")
                     for entry in state if entry["slug"] not in {*GROUP_CORE, "ops", "core"}]
            await reply(message, panel("Plugin inventory", subtitle="Read-only runtime inspection",
                table=Table(headers=("Plugin", "Runtime"), rows=tuple(rows)),
                note="Runtime availability is not group activation. Approval and runtime changes remain Owner-only; group activation requires group-admin rights."))
            return
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
        from ...platform.policy import is_worker
        if is_worker(ctx.settings) and args and args[0].lower() not in {row['slug'] for row in runtime.state()}:
            await reply(message, 'That plugin is not part of this worker. Change its selection through the controller first.')
            return
        if len(args) == 2 and args[1].lower() in ("approve", "revoke"):
            from ...platform.plugin_access import AccessError
            service = getattr(ctx, "plugin_access", None)
            if service is None:
                await reply(message, "Database plugin access is unavailable.")
                return
            try:
                operation = service.approve if args[1].lower() == "approve" else service.revoke
                await operation(args[0].lower(), actor_id=message.from_user.id)
                await reply(message, "Global plugin approval updated. For approval: a group admin must now open /plugins in the target group and tap Activate. Revocation removes group access; runtime on/off is a separate setting.")
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
        try:
            changed = runtime.enable(slug) if action == 'on' else runtime.disable(slug)
        except ValueError as exc:
            await reply(message, str(exc))
            return
        except RuntimeError:
            await reply(message, 'Runtime change could not be confirmed. Check /errors and refresh /plugins before retrying; no success is claimed.')
            return
        if not changed:
            current = next(row for row in runtime.state() if row['slug'] == slug)
            if action == 'on' and not current.get('tracked_handlers'):
                explanation = f'Cannot start {slug}: {_idle_reason(current)}. Configure this bot and restart with authorization.'
            else:
                explanation = f'{slug} is already {action}. No duplicate handlers were attached.'
            await reply(message, html.escape(explanation) +
                        (f' Group use still requires <code>/plugin {slug} approve</code> and group-admin activation in /plugins.' if action == 'on' else ' Group approval is separate from runtime state.'))
            return
        if events is not None:
            events.emit(
                "plugin", slug=slug, action=action, by=getattr(message.from_user, "id", None)
            )
        await reply(message, 
            f"Plugin <code>{slug}</code> is now {'enabled' if action == 'on' else 'disabled'}."
            + (
                "\nIts handlers are detached, so none of its commands respond."
                if action == "off"
                else f"\nRuntime only: this does not approve or activate group use. Next: <code>/plugin {slug} approve</code>, then a group admin activates it in /plugins."
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
            await reply(message, "Database incident history could not be read.")
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
        await reply(message, f"Log channel set to <b>{html.escape(str(title))}</b> (<code>{target}</code>). Settings saved.")


    async def log(client, message):
        if not await _owner_gate(message):
            return
        logbook = getattr(ctx, "logbook", None)
        if logbook is None:  # pragma: no cover
            return
        args=(getattr(message,'text','') or '').split()[1:]
        if args not in ([],['test']):
            await reply(message,'Usage: /log or /log test (sends one diagnostic event to the saved destination).')
            return
        try:
            await logbook.hydrate()
        except LogSettingsError as exc:
            await reply(message, html.escape(str(exc)))
            return
        if args==['test']:
            confirmed=await logbook.post('log_test',source='owner diagnostic',status='Telegram delivery test')
            status=logbook.delivery_status()
            detail=html.escape(str(status.get('error_type') or status['last_result']))
            hint=html.escape(status.get('hint') or 'Check saved destination and bot posting permissions.')
            await reply(message,'Log test delivered to Telegram.' if confirmed else f'Log test NOT delivered ({detail}). {hint}')
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
            "Settings: saved configuration",
            f"Events recorded: {events.count() if events is not None else 0}",
        ]
        status=logbook.delivery_status()
        lines.extend([
            f"Telegram posts this process: {status['sent']} sent / {status['failed']} failed",
            f"Pending: {status['pending']} / dropped: {status['dropped']}",
            f"Last delivery: {html.escape(status['last_result'])}" + (f" ({html.escape(status['error_type'])})" if status['error_type'] else ''),
            'Recorded events are not delivery receipts. Run <code>/log test</code> to check posting now.',
        ])
        startup=status['startup']
        lines.append('Startup post: '+html.escape(startup['last_result'])+(f" ({html.escape(startup['error_type'])})" if startup['error_type'] else ''))
        if startup.get('hint'):
            lines.append(html.escape(startup['hint']))
        if status.get('hint'):
            lines.append('Last delivery hint: '+html.escape(status['hint']))
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

    handlers = {
        **sudo_commands(capabilities, _owner_gate),
        "restart": restart,
        "bstats": bstats,
        "mychats": mychats,
        "massban": massban,
        "broadcast": broadcast,
        "watchdog": watchdog,
        "plugins": plugins,
        "db": db,
        "plugin": plugin,
        "events": show_events,
        "errors": errors,
        "setlog": setlog,

        "log": log,
    }

    from dataclasses import replace
    from ...platform.policy import is_worker
    if is_worker(ctx.settings):
        handlers = {name: handler for name, handler in handlers.items() if name in ('plugins', 'plugin')}
        return replace(MANIFEST, name='Worker plugin controls', clone_compatible=True,
                       description='Owner approval and group activation for selected worker tools.',
                       permissions=('messages.read', 'messages.send', 'plugins.manage'),
                       commands=tuple(handlers)), handlers
    return MANIFEST, handlers
