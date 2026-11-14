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
        await message.reply(
            "<b>Agent</b>\n"
            f"Version {__version__}\n"
            f"Modules: {modules}\n"
            f"Commands: {commands}\n\n"
            "A single bot with one job queue, one file store and one link signer — "
            "modules share them instead of running their own."
        )

    async def status(_client, message):
        modules, commands = _registry_summary()
        lines = ["<b>Runtime status</b>", f"Version: {__version__}"]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            lines.extend(
                [
                    f"State: {snapshot.state}",
                    f"Uptime: {format_uptime(snapshot.uptime_seconds)}",
                    f"Probes: {snapshot.probes} ({snapshot.failures} failed)",
                    f"Latency: {snapshot.latency_ms} ms" if snapshot.latency_ms is not None else "Latency: n/a",
                ]
            )
        if ctx.jobs is not None:
            active = ctx.jobs.active()
            lines.append(f"Jobs running: {len(active)}")
        lines.append(f"Modules: {modules}")
        lines.append(f"Commands: {commands}")
        user = getattr(message, "from_user", None)
        if user is not None and ctx.storage is not None:
            lines.append(f"Your storage: {_human_bytes(ctx.storage.usage(user.id))}")
        await message.reply("\n".join(lines))

    async def cancel(_client, message):
        user = getattr(message, "from_user", None)
        if user is None or ctx.jobs is None:
            await message.reply("Nothing to cancel.")
            return
        stopped = 0
        for job in ctx.jobs.active():
            if job.owner_id != user.id:
                continue
            stopped += bool(ctx.jobs.cancel(job.id, owner_id=user.id))
        if stopped:
            await message.reply(f"Cancelled {stopped} job(s).")
        else:
            await message.reply("Nothing was running, so nothing was cancelled.")

    async def owner(_client, message):
        owner_id = ctx.settings.owner_id
        if owner_id is None:
            await message.reply(
                "No owner is configured. Set <code>OWNER_ID</code> to your Telegram "
                "user id and restart to enable this command."
            )
            return
        user = getattr(message, "from_user", None)
        if user is None or int(user.id) != int(owner_id):
            await message.reply(OWNER_ONLY)
            return
        modules, commands = _registry_summary()
        lines = ["<b>Owner panel</b>", f"Version: {__version__}"]
        if ctx.monitor is not None:
            snapshot = ctx.monitor.snapshot()
            lines.append(f"Uptime: {format_uptime(snapshot.uptime_seconds)}")
            lines.append(f"State: {snapshot.state}")
            if snapshot.last_error:
                lines.append(f"Last error: {snapshot.last_error[:120]}")
        if ctx.jobs is not None:
            lines.append(f"Jobs running: {len(ctx.jobs.active())}")
        lines.append(f"Modules: {modules}")
        lines.append(f"Commands: {commands}")
        lines.append(f"Data dir: <code>{ctx.settings.data_dir}</code>")
        await message.reply("\n".join(lines))

    return MANIFEST, {
        "menu": menu,
        "about": about,
        "status": status,
        "cancel": cancel,
        "owner": owner,
    }
