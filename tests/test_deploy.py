"""Deployment-shape regressions: read-only data dir, lease degradation, log hygiene."""

import logging
import pathlib


from agent.bot import AgentBot
from agent.config import Settings
from agent.platform.instance import InstanceLease
from agent.platform.paths import resolve_data_dir

ENV = {
    "BOT_TOKEN": "8801481578:AAHsecretHalfThatMustNotLeak_1234567890",
    "API_ID": "38066209",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


def block(path, monkeypatch, *, blocked: pathlib.Path):
    """Make mkdir under *blocked* fail, as a root-owned /app does for uid 10001."""
    real_mkdir = pathlib.Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if str(self).startswith(str(blocked)):
            raise PermissionError(13, "Permission denied", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "mkdir", fake_mkdir)


# --- data directory --------------------------------------------------------


def test_a_writable_data_dir_is_used_as_is(tmp_path):
    resolved, ok = resolve_data_dir(tmp_path / "data")

    assert ok is True
    assert resolved == tmp_path / "data"


def test_a_read_only_data_dir_falls_back_instead_of_crashing(tmp_path, monkeypatch):
    blocked = tmp_path / "app"
    block(tmp_path / "app", monkeypatch, blocked=blocked)

    resolved, ok = resolve_data_dir(blocked / "data")

    assert ok is False
    assert resolved != blocked / "data"
    assert "agent-data" in str(resolved)


# --- the failure that took the deploy down ---------------------------------


def test_the_lease_degrades_when_it_cannot_write(tmp_path, monkeypatch):
    lease = InstanceLease(tmp_path / "data" / "instance.lock", owner="deploy")

    def deny(self):
        raise PermissionError(13, "Permission denied", "data")

    monkeypatch.setattr(InstanceLease, "_write", deny)

    # It must let the bot start rather than take the whole deploy down...
    assert lease.try_acquire() is True
    # ...while being explicit that protection is gone.
    assert lease.degraded is True
    assert lease.state()["degraded"] is True


def test_the_lease_reports_normal_state_when_it_can_write(tmp_path):
    lease = InstanceLease(tmp_path / "lock", owner="deploy")

    assert lease.try_acquire() is True
    assert lease.degraded is False
    assert lease.state()["held_by_us"] is True


# --- log hygiene -----------------------------------------------------------


def test_building_the_client_does_not_log_the_api_id_or_token(caplog):
    settings = Settings.from_env(ENV)

    with caplog.at_level(logging.INFO):
        AgentBot(settings).build()

    assert "38066209" not in caplog.text
    assert "api_id=" not in caplog.text
    assert ENV["BOT_TOKEN"] not in caplog.text
    # The token is still identifiable for operators: prefix, then dashes.
    assert "8801481578:--------" in caplog.text


def test_the_masked_token_keeps_the_id_and_hides_the_secret():
    settings = Settings.from_env(ENV)

    masked = settings.masked_token

    assert masked.startswith("8801481578:")
    assert "AAHsecretHalfThatMustNotLeak" not in masked


def test_startup_configuration_log_omits_the_api_id(capsys, monkeypatch):
    import start

    monkeypatch.setenv("BOT_TOKEN", ENV["BOT_TOKEN"])
    monkeypatch.setenv("API_ID", ENV["API_ID"])
    monkeypatch.setenv("API_HASH", ENV["API_HASH"])

    code = start.main(["--check"])
    printed = capsys.readouterr().out

    assert code == 0
    assert "Configuration loaded" in printed
    # The api_id used to be printed here; it is not a credential, but it does
    # not belong in a build log either.
    assert "38066209" not in printed
    assert ENV["BOT_TOKEN"] not in printed
    assert "8801481578:--------" in printed
