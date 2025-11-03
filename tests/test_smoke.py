"""Smoke tests for the MVP scaffolding."""

from contextlib import contextmanager
from importlib import reload
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - import-time guard
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402  (import after path adjustment)
from slack_workflow_engine import config  # noqa: E402


def test_health_endpoint_returns_ok(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U111,U222")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    config.get_settings.cache_clear()

    reload(app_module)
    flask_app = app_module.create_app()

    with flask_app.test_client() as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["config"] == "valid"
        assert data["db"] == "up"
        assert "version" in data


def test_health_endpoint_reports_db_down(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U111,U222")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    config.get_settings.cache_clear()

    reload(app_module)
    flask_app = app_module.create_app()

    @contextmanager
    def failing_session_scope():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(app_module, "session_scope", failing_session_scope)

    with flask_app.test_client() as client:
        response = client.get("/healthz")
        data = response.get_json()
        assert response.status_code == 503
        assert data["ok"] is False
        assert data["db"] == "down"
        assert "db_error" in data
