"""Health state machine, watchdog probes and the health endpoint."""

import asyncio

import pytest

from agent.config import Settings
from agent.health import DEGRADED, DOWN, HEALTHY, STARTING, HealthMonitor
from agent.health_server import build_app, health_payload, status_code
from agent.watchdog import Watchdog


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


# --- state machine ---------------------------------------------------------


def test_fresh_monitor_is_starting():
    monitor = HealthMonitor()

    assert monitor.state() == STARTING
    assert monitor.snapshot().probes == 0


def test_successful_probe_means_healthy():
    clock = FakeClock()
    monitor = HealthMonitor(clock=clock)

    monitor.record_success(latency_ms=42)

    assert monitor.state() == HEALTHY
    assert monitor.snapshot().latency_ms == 42


def test_consecutive_failures_mark_down_at_threshold():
    monitor = HealthMonitor(failure_threshold=3)
    monitor.record_success()

    for _ in range(3):
        monitor.record_failure("boom")

    assert monitor.state() == DOWN
    assert monitor.snapshot().last_error == "boom"


def test_one_failure_is_degraded_not_down():
    monitor = HealthMonitor(failure_threshold=3)
    monitor.record_success()

    monitor.record_failure("blip")

    assert monitor.state() == DEGRADED


def test_success_clears_consecutive_failures():
    monitor = HealthMonitor(failure_threshold=3)
    monitor.record_failure("a")
    monitor.record_failure("b")

    monitor.record_success()

    assert monitor.state() == HEALTHY
    assert monitor.snapshot().failures == 2  # lifetime count is kept


def test_state_ages_from_last_success():
    clock = FakeClock()
    monitor = HealthMonitor(degraded_after=60, down_after=300, clock=clock)
    monitor.record_success()

    clock.advance(120)
    assert monitor.state() == DEGRADED

    clock.advance(300)
    assert monitor.state() == DOWN


def test_activity_is_tracked_but_never_decides_health():
    clock = FakeClock()
    monitor = HealthMonitor(clock=clock)
    monitor.record_success()

    clock.advance(30)
    monitor.record_activity("start")

    snapshot = monitor.snapshot()
    assert snapshot.seconds_since_activity == 0
    assert monitor.state() == HEALTHY


def test_snapshot_is_json_ready():
    monitor = HealthMonitor()
    monitor.record_success(latency_ms=3)

    data = monitor.snapshot().as_dict()

    assert set(data) >= {"state", "uptime_seconds", "probes", "failures", "latency_ms"}
    assert all(isinstance(v, (int, float, str, type(None))) for v in data.values())


# --- watchdog --------------------------------------------------------------


class FakeClient:
    def __init__(self, *, fail=False, connected=True):
        self.fail = fail
        self.is_connected = connected
        self.connects = 0

    async def connect(self):
        self.connects += 1
        self.is_connected = True

    async def get_me(self):
        if self.fail:
            raise ConnectionResetError("link down")
        return object()


def test_probe_success_records_latency():
    monitor = HealthMonitor()
    dog = Watchdog(FakeClient(), monitor, interval=0.01)

    assert asyncio.run(dog.probe()) is True
    assert monitor.state() == HEALTHY


def test_probe_failure_records_error():
    monitor = HealthMonitor(failure_threshold=5)
    dog = Watchdog(FakeClient(fail=True), monitor, interval=0.01)

    assert asyncio.run(dog.probe()) is False
    assert "ConnectionResetError" in monitor.snapshot().last_error


def test_probe_reconnects_a_dropped_socket():
    client = FakeClient(connected=False)
    dog = Watchdog(client, HealthMonitor(), interval=0.01)

    asyncio.run(dog.probe())

    assert client.connects == 1


def test_watchdog_requests_restart_after_fatal_failures():
    monitor = HealthMonitor(failure_threshold=10)
    calls = []
    dog = Watchdog(FakeClient(fail=True), monitor, interval=0.01, fatal_after=2, on_fatal=lambda: calls.append(1))

    async def run_it():
        await dog.run(asyncio.Event())

    asyncio.run(run_it())

    assert calls == [1]


def test_watchdog_stops_when_asked():
    monitor = HealthMonitor()
    dog = Watchdog(FakeClient(), monitor, interval=0.01)
    stop = asyncio.Event()

    async def run_it():
        stop.set()
        await dog.run(stop)

    asyncio.run(run_it())

    assert monitor.snapshot().probes == 0


# --- endpoint --------------------------------------------------------------


def test_health_payload_reports_state_and_version():
    monitor = HealthMonitor()
    monitor.record_success()

    payload = health_payload(monitor)

    assert payload["ok"] is True
    assert payload["state"] == HEALTHY
    assert "version" in payload


def test_down_state_returns_503_so_platform_restarts():
    monitor = HealthMonitor(failure_threshold=1)
    monitor.record_failure("dead")

    assert monitor.state() == DOWN
    assert status_code(DOWN) == 503
    assert status_code(HEALTHY) == 200


def test_app_registers_live_and_health_routes():
    app = build_app(HealthMonitor())

    routes = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in routes
    assert "/health/live" in routes


# --- configuration ---------------------------------------------------------


def test_health_port_is_optional():
    assert Settings.from_env(ENV).health_port is None


def test_health_port_can_be_set_explicitly():
    assert Settings.from_env({**ENV, "HEALTH_PORT": "8080"}).health_port == 8080


def test_platform_port_enables_the_endpoint():
    # Render web services provide PORT; workers do not.
    assert Settings.from_env({**ENV, "PORT": "10000"}).health_port == 10000


def test_health_port_wins_over_platform_port():
    assert Settings.from_env({**ENV, "PORT": "10000", "HEALTH_PORT": "8080"}).health_port == 8080


@pytest.mark.parametrize("value", ["abc", "0", "70000", ""])
def test_invalid_ports_are_ignored(value):
    assert Settings.from_env({**ENV, "HEALTH_PORT": value}).health_port is None


def test_watchdog_defaults_are_sane():
    settings = Settings.from_env(ENV)

    assert settings.watchdog_interval == 30.0
    assert settings.watchdog_timeout == 20.0
    assert settings.watchdog_fatal_after == 5


# --- exit-code contract ----------------------------------------------------


def test_main_exits_1_when_the_watchdog_gives_up(monkeypatch):
    import start

    class DyingBot:
        def __init__(self, settings):
            self.settings = settings
            self.handler_count = 0
            self.fatal_reason = None

        async def run(self):
            self.fatal_reason = "telegram unreachable"

    monkeypatch.setattr(start, "AgentBot", DyingBot)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    assert start.main([]) == 1


def test_bot_marks_fatal_when_watchdog_fires():
    from agent.bot import AgentBot

    bot = AgentBot(Settings.from_env(ENV))
    stop = asyncio.Event()

    bot._request_restart(stop)

    assert bot.fatal_reason == "telegram unreachable"
    assert stop.is_set()


def test_alive_json_and_readiness_reflect_real_probe_state():
    from aiohttp.test_utils import TestClient, TestServer
    async def scenario():
        clock = FakeClock()
        monitor = HealthMonitor(clock=clock, degraded_after=60, down_after=120)
        async with TestClient(TestServer(build_app(monitor))) as client:
            response = await client.get('/')
            body = await response.json()
            assert body['bot'] == 'Meiko' and body['status'] == 'starting'
            assert body['heartbeat_age'] is None
            assert (await client.get('/health/ready')).status == 503
            monitor.record_success()
            body = await (await client.get('/alive')).json()
            assert body['status'] == 'alive' and body['heartbeat_age'] == 0
            assert 'time' in body and body['uptime'] == 0
            assert (await client.get('/health/ready')).status == 200
            clock.advance(61)
            assert (await client.get('/health/ready')).status == 503
            clock.advance(60)
            body = await (await client.get('/alive')).json()
            assert body['status'] == 'stale'
            assert (await client.get('/health')).status == 503
            assert (await client.get('/health/live')).status == 200
    asyncio.run(scenario())
