"""Tests for configuration helpers."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine import config  # noqa: E402


def _seed_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1, U2 ,U3")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    config.get_settings.cache_clear()


def test_get_settings_parses_expected_fields(monkeypatch):
    _seed_env(monkeypatch)

    settings = config.get_settings()

    assert settings.bot_token == "token"
    assert settings.signing_secret == "secret"
    assert settings.approver_user_ids == ["U1", "U2", "U3"]
    assert settings.database_url == "sqlite:///local.db"


def test_missing_environment_variables_raise_runtime_error(monkeypatch):
    # Clear all required env variables
    for var in (
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
        "APPROVER_USER_IDS",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    config.get_settings.cache_clear()

    with pytest.raises(RuntimeError) as err:
        config.get_settings()

    message = str(err.value)
    assert "SLACK_BOT_TOKEN" in message
    assert "SLACK_SIGNING_SECRET" in message
    assert "APPROVER_USER_IDS" in message
    assert "DATABASE_URL" in message
