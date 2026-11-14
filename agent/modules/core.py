"""Core module — the everyday commands Meikoagent's core and owner routers expose.

``menu``, ``about``, ``status``, ``cancel`` and ``owner`` join the existing
``/start``, ``/help`` and ``/ping``. Two of them are implemented more strictly
than the reference, because the reference version would be a fake control:

* ``/cancel`` there answers "Cancelled" without cancelling anything; here it
  cancels the caller's real jobs and reports how many actually stopped.
* ``/status`` reports this process's real counters (uptime, probes, failures,
  queued jobs) read from the live health monitor, not placeholder numbers.

``/owner`` needs ``OWNER_ID``. Without it the command says so instead of
guessing an owner.
"""

from __future__ import annotations

import logging

from .. import __version__
from ..platform.manifest import PluginManifest
from ..ui.screens import format_uptime, welcome_screen
from ..platform.credits import NOTICE, rows
from ..ui.tables import Table, kv_table, panel
from ..utils.rich import reply

logger = logging.getLogger(__name__)

MANIFEST = PluginManifest(
    slug="core",
    name="Core extras",
    version="1.0.0",
    description="Menu, about, runtime status, job cancellation and the owner panel.",
    commands=("menu", "about", "status", "cancel", "owner"),
    permissions=("messages.read",),
    scope="all",
)

OWNER_ONLY = "This command is reserved for the bot owner."


def _human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"  # pragma: no cover - unreachable


def build(ctx):
    """Wire the core-extras commands to the shared context."""

    def _registry_summary() -> tuple[str, int]:
        registry = ctx.registry
        if registry is None:  # pragma: no cover - always set by the bot
            return "unknown", 0
        manifests = registry.manifests()
        enabled = [m.name for m in manifests if registry.is_enabled(m.slug)]
        return ", ".join(enabled) or "none", len(registry.active_commands())

    async def menu(_client, message):
        user = getattr(message, "from_user", None)
        await ctx.sender.send(message.chat.id, welcome_screen(user, ctx.theme))

    async def about(_client, message):
        modules, commands = _registry_summary()
        await reply(
            message,
            panel(
                "About Agent",
                icon=ctx.theme.emoji("sparkles"),
                subtitle=f"Version <b>{__version__}</b> · {commands} commands",
                lines=[
                    f"Modules: {modules}",
                    "One job queue, one file store, one link signer — modules share "
                    "them instead of running their own.",
                ],
                table=Table(
                    headers=("Project", "What it gave"),
                    rows=tuple(rows()),
                ),
                note=NOTICE,
                footer=(
                    "Full list with licences: <code>docs/CREDITS.md</code> · "
                    "runtime: wzgram + richgram"
                ),
            ),
        )

    async def status(_client, message):
        modules, commands = _registry_summary()
        rows: list[tuple[str, str]] = [("Version", __version__)]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            rows.extend(
                [
                    ("State", snapshot.state),
                    ("Uptime", format_uptime(snapshot.uptime_seconds)),
                    ("Probes", f"{snapshot.probes} ({snapshot.failures} failed)"),
                    (
                        "Latency",
                        f"{snapshot.latency_ms} ms"
                        if snapshot.latency_ms is not None
                        else "no probe yet",
                    ),
                ]
            )
        if ctx.jobs is not None:
            rows.append(("Jobs running", str(len(ctx.jobs.active()))))
        rows.append(("Modules", modules))
        rows.append(("Commands", str(commands)))
        user = getattr(message, "from_user", None)
        if user is not None and ctx.storage is not None:
            rows.append(("Your storage", _human_bytes(ctx.storage.usage(user.id))))
        await reply(message,
            panel(
                "Runtime status",
                icon=ctx.theme.emoji("stats"),
                subtitle="Read from this process, not from a cache.",
                table=kv_table(rows),
                footer="<code>/ping</code> checks the link, <code>/owner</code> shows the owner panel.",
            )
        )

    async def cancel(_client, message):
        user = getattr(message, "from_user", None)
        if user is None or ctx.jobs is None:
            await reply(message, "Nothing to cancel.")
            return
        stopped = 0
        for job in ctx.jobs.active():
            if job.owner_id != user.id:
                continue
            stopped += bool(ctx.jobs.cancel(job.id, owner_id=user.id))
        if stopped:
            await reply(message, f"Cancelled {stopped} job(s).")
        else:
            await reply(message, "Nothing was running, so nothing was cancelled.")

    async def owner(_client, message):
        owner_id = ctx.settings.owner_id
        if owner_id is None:
            await reply(message,
                "No owner is configured. Set <code>OWNER_ID</code> to your Telegram "
                "user id and restart to enable this command."
            )
            return
        user = getattr(message, "from_user", None)
        if user is None or int(user.id) != int(owner_id):
            await reply(message, OWNER_ONLY)
            return
        modules, commands = _registry_summary()
        rows: list[tuple[str, str]] = [("Version", __version__)]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            rows.append(("Uptime", format_uptime(snapshot.uptime_seconds)))
            rows.append(("State", snapshot.state))
            if snapshot.last_error:
                rows.append(("Last error", snapshot.last_error[:120]))
        if ctx.jobs is not None:
            rows.append(("Jobs running", str(len(ctx.jobs.active()))))
        rows.append(("Modules", modules))
        rows.append(("Commands", str(commands)))
        rows.append(("Data dir", str(ctx.settings.data_dir)))
        await reply(message,
            panel(
                "Owner panel",
                icon=ctx.theme.emoji("bot"),
                subtitle="Controls that only the bot owner may use.",
                table=kv_table(rows),
                note=(
                    "<code>/plugins</code> · <code>/plugin &lt;slug&gt; on|off</code> · "
                    "<code>/events</code> · <code>/watchdog</code> · <code>/restart</code>"
                ),
                footer="Owner only.",
            )
        )

    return MANIFEST, {
        "menu": menu,
        "about": about,
        "status": status,
        "cancel": cancel,
        "owner": owner,
    }
