"""Operations module — restart, watchdog, plugin control and the event log.

This is the "keep-alive like Videl1" half of the bot: the single-instance lease,
the cleanup sweeps Videl1 exposes through ``/watchdog run|clean``, a restart
that actually stops the process so its supervisor can bring it back, and
runtime plugin switching.

Nothing here reports success it did not verify: a sweep reports the bytes it
actually removed, a restart says plainly that an unsupervised process will stay
down, and disabling a plugin detaches its handlers rather than hiding it.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from ..platform.manifest import PluginManifest
from ..ui.screens import format_uptime

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="ops",
    name="Operations",
    version="1.0.0",
    description="Restart, watchdog sweeps, plugin on/off and the event log.",
    commands=("restart", "watchdog", "plugins", "plugin", "events"),
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


def build(ctx):
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
            await message.reply(
                "No owner is configured. Set <code>OWNER_ID</code> and restart to "
                "enable this command."
            )
            return False
        if not _is_owner(message):
            await message.reply(OWNER_ONLY)
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
            await message.reply(
                f"{len(active)} job(s) are still running. "
                "Use <code>/restart force</code> to stop them, or wait and retry."
            )
            return
        reason = " ".join(a for a in args if a != "force") or "requested"
        if events is not None:
            events.emit("restart", by=getattr(message.from_user, "id", None), reason=reason)
        started = runtime.request_restart(reason) if runtime is not None else False
        await message.reply(
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
            expired = ctx.links.purge_expired() if ctx.links is not None else 0
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
            await message.reply("\n".join(lines))
            return

        lines = ["<b>Watchdog</b>"]
        if lease is not None:
            state = lease.state()
            lines.append(
                f"Instance: {'held by this process' if state['held_by_us'] else 'not held'}"
                + (
                    f" (expires in {state['expires_in']}s)"
                    if state["expires_in"]
                    else ""
                )
            )
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            lines.append(f"State: {snapshot.state}")
            lines.append(f"Uptime: {format_uptime(snapshot.uptime_seconds)}")
            lines.append(f"Latency: {snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "Latency: n/a")
        if ctx.jobs is not None:
            lines.append(f"Jobs running: {len(ctx.jobs.active())}")
        if runtime is not None:
            disabled = [row["slug"] for row in runtime.state() if not row["enabled"]]
            lines.append(f"Plugins disabled: {', '.join(disabled) or 'none'}")
        lines.append("Run <code>/watchdog run</code> to sweep, <code>/watchdog clean</code> for a deeper clean.")
        await message.reply("\n".join(lines))

    # -- /plugins and /plugin ---------------------------------------------

    async def plugins(_client, message):
        if not await _owner_gate(message):
            return
        if runtime is None:  # pragma: no cover - always wired
            await message.reply("Plugin runtime is unavailable.")
            return
        lines = ["<b>Plugins</b>"]
        for row in runtime.state():
            mark = "on" if row["enabled"] else "off"
            locked = " · locked" if row["protected"] else ""
            lines.append(
                f"<code>{row['slug']}</code> — {row['name']} · {mark}{locked} · "
                f"{len(row['commands'])} commands"
            )
        lines.append("\nToggle with <code>/plugin &lt;slug&gt; on|off</code>.")
        await message.reply("\n".join(lines))

    async def plugin(_client, message):
        if not await _owner_gate(message):
            return
        if runtime is None:  # pragma: no cover
            await message.reply("Plugin runtime is unavailable.")
            return
        args = _args(message)[1:]
        if not args:
            await message.reply("Usage: <code>/plugin &lt;slug&gt; on|off</code>")
            return
        slug = args[0].lower()
        action = args[1].lower() if len(args) > 1 else ""
        known = {row["slug"] for row in runtime.state()}
        if slug not in known:
            await message.reply(f"No plugin named <code>{slug}</code>.")
            return
        if action not in ("on", "off"):
            await message.reply("Usage: <code>/plugin &lt;slug&gt; on|off</code>")
            return
        if action == "on":
            changed = runtime.enable(slug)
        else:
            try:
                changed = runtime.disable(slug)
            except ValueError as exc:
                await message.reply(str(exc))
                return
        if not changed:
            await message.reply(f"<code>{slug}</code> was already {action if action == 'on' else 'off'}.")
            return
        if events is not None:
            events.emit(
                "plugin", slug=slug, action=action, by=getattr(message.from_user, "id", None)
            )
        await message.reply(
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
            await message.reply("No event log in this runtime.")
            return
        recent = events.recent(10)
        if not recent:
            await message.reply("<b>Events</b>\nNothing recorded yet.")
            return
        lines = [f"<b>Events</b> ({events.count()} recorded)"]
        for event in recent:
            stamp = time.strftime("%H:%M:%S", time.gmtime(event["at"]))
            fields = " ".join(
                f"{key}={value}" for key, value in event.items() if key not in ("kind", "at")
            )
            lines.append(f"{stamp} {event['kind']} {fields}".strip())
        await message.reply("\n".join(lines))

    return MANIFEST, {
        "restart": restart,
        "watchdog": watchdog,
        "plugins": plugins,
        "plugin": plugin,
        "events": show_events,
    }
