"""Agent — optional HTTP health endpoint.

Disabled by default: a polling bot on a *Background Worker* needs no HTTP
server at all. Set ``HEALTH_PORT`` (or run as a web service, where the
platform provides ``PORT``) to expose ``/health`` and ``/health/live``.

This endpoint answers real platform checks. Nothing pings itself — that
distinction is the whole point (see ``docs``/README "Health").
"""

from __future__ import annotations

import logging

from . import __version__
from .health import DEGRADED, DOWN, STARTING, HealthMonitor

logger = logging.getLogger(__name__)

try:  # aiohttp is only needed when the endpoint is enabled
    from aiohttp import web
except ImportError:  # pragma: no cover - exercised only on a broken install
    web = None


def health_payload(monitor: HealthMonitor) -> dict:
    """JSON body for ``/health`` (pure, so it is easy to test)."""
    snapshot = monitor.snapshot()
    payload = snapshot.as_dict()
    payload["version"] = __version__
    payload["ok"] = snapshot.state not in (DOWN,)
    return payload


def status_code(state: str) -> int:
    """HTTP status for a health state.

    ``503`` when down so the platform's own health check restarts the
    container — the honest alternative to pinging ourselves awake.
    """
    return 503 if state == DOWN else 200


def build_app(monitor: HealthMonitor):
    """Build the aiohttp application (raises if aiohttp is unavailable)."""
    if web is None:  # pragma: no cover
        raise RuntimeError("aiohttp is required for the health endpoint.")

    async def root(_request):
        return web.Response(text=f"Agent {__version__} is running.")

    async def health(_request):
        state = monitor.state()
        return web.json_response(health_payload(monitor), status=status_code(state))

    async def live(_request):
        # Process liveness only: it never touches Telegram, so a slow probe
        # cannot get a healthy container killed.
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    app.router.add_get("/health/live", live)
    return app


async def start_health_server(monitor: HealthMonitor, port: int, host: str = "0.0.0.0"):
    """Start the endpoint; returns the runner (or ``None`` when unavailable)."""
    if web is None:  # pragma: no cover
        logger.warning("HEALTH_PORT is set but aiohttp is not installed; skipping health server.")
        return None

    runner = web.AppRunner(build_app(monitor), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info("Health endpoint listening on http://%s:%d/health", host, port)
    return runner


async def stop_health_server(runner) -> None:
    if runner is None:
        return
    await runner.cleanup()
    logger.info("Health endpoint stopped.")


__all__ = [
    "DEGRADED",
    "DOWN",
    "STARTING",
    "build_app",
    "health_payload",
    "start_health_server",
    "status_code",
    "stop_health_server",
]
