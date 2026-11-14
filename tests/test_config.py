"""Configuration loading and validation."""

import pytest

from agent.config import ConfigError, Settings

VALID_ENV = {
    "BOT_TOKEN": "123456789:AAHfakeTokenValueForTests_1234567890abc",
    "API_ID": "1234567",
    "API_HASH": "0123456789abcdef0123456789abcdef",
}


def test_loads_valid_environment():
    settings = Settings.from_env(VALID_ENV)

    assert settings.bot_token == VALID_ENV["BOT_TOKEN"]
    assert settings.api_id == 1234567
    assert settings.api_hash == VALID_ENV["API_HASH"]
    assert settings.session_name == "agent"


def test_token_is_masked_for_logs():
    settings = Settings.from_env(VALID_ENV)

    assert settings.masked_token == "123456789:--------"
    assert VALID_ENV["BOT_TOKEN"].split(":")[1] not in settings.masked_token


def test_missing_bot_token_is_reported():
    env = {k: v for k, v in VALID_ENV.items() if k != "BOT_TOKEN"}

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env(env)

    assert "BOT_TOKEN is missing" in str(excinfo.value)


def test_all_missing_variables_are_reported_together():
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({})

    message = str(excinfo.value)
    assert "BOT_TOKEN" in message
    assert "API_ID" in message
    assert "API_HASH" in message


def test_malformed_token_is_rejected():
    env = {**VALID_ENV, "BOT_TOKEN": "not-a-token"}

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env(env)

    assert "malformed" in str(excinfo.value)


def test_non_numeric_api_id_is_rejected():
    env = {**VALID_ENV, "API_ID": "abc"}

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env(env)

    assert "API_ID must be an integer" in str(excinfo.value)


def test_non_positive_api_id_is_rejected():
    env = {**VALID_ENV, "API_ID": "0"}

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env(env)

    assert "positive integer" in str(excinfo.value)


def test_bad_api_hash_is_rejected():
    env = {**VALID_ENV, "API_HASH": "too-short"}

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env(env)

    assert "32 hexadecimal" in str(excinfo.value)


def test_whitespace_is_tolerated():
    env = {key: f"  {value}  " for key, value in VALID_ENV.items()}

    settings = Settings.from_env(env)

    assert settings.api_id == 1234567
    assert settings.api_hash == VALID_ENV["API_HASH"]
