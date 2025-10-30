"""Tests for the Flask application factory."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from flask import Response

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config, security  # noqa: E402


class DummyHandler:
    called = False

    def __init__(self, bolt_app):
        self.bolt_app = bolt_app

    def handle(self, _request):
        DummyHandler.called = True
        return Response("ok", status=200)


def _seed_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    config.get_settings.cache_clear()


def _signed_headers(secret: str, body: str, timestamp: str) -> dict[str, str]:
    signature = security.compute_signature(secret, timestamp, body)
    return {
        security.SLACK_SIGNATURE_HEADER: signature,
        security.SLACK_TIMESTAMP_HEADER: timestamp,
    }


def test_slack_events_route_uses_handler(monkeypatch):
    _seed_env(monkeypatch)

    DummyHandler.called = False
    monkeypatch.setattr(app_module, "SlackRequestHandler", DummyHandler)
    flask_app = app_module.create_app()

    body = "{}"
    timestamp = "1700000000"
    monkeypatch.setattr(security, "time", SimpleNamespace(time=lambda: int(timestamp)))
    headers = _signed_headers("secret", body, timestamp)

    client = flask_app.test_client()
    response = client.post(
        "/slack/events",
        data=body,
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.data == b""
    assert DummyHandler.called is True


def test_invalid_signature_returns_unauthorised(monkeypatch):
    _seed_env(monkeypatch)

    DummyHandler.called = False
    monkeypatch.setattr(app_module, "SlackRequestHandler", DummyHandler)
    flask_app = app_module.create_app()

    body = "{}"
    timestamp = "1700000000"
    monkeypatch.setattr(security, "time", SimpleNamespace(time=lambda: int(timestamp)))

    client = flask_app.test_client()
    response = client.post(
        "/slack/events",
        data=body,
        content_type="application/json",
        headers={
            security.SLACK_SIGNATURE_HEADER: "v0=invalid",
            security.SLACK_TIMESTAMP_HEADER: timestamp,
        },
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_signature"
    assert DummyHandler.called is False


def test_stale_timestamp_rejected(monkeypatch):
    _seed_env(monkeypatch)

    DummyHandler.called = False
    monkeypatch.setattr(app_module, "SlackRequestHandler", DummyHandler)
    flask_app = app_module.create_app()

    body = "{}"
    request_timestamp = "100"
    monkeypatch.setattr(security, "time", SimpleNamespace(time=lambda: 2000))
    headers = _signed_headers("secret", body, request_timestamp)

    client = flask_app.test_client()
    response = client.post(
        "/slack/events",
        data=body,
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_signature"
    assert DummyHandler.called is False


def test_slack_events_ack_is_immediate(monkeypatch):
    _seed_env(monkeypatch)

    def slow_handle(_request):
        import time

        time.sleep(0.2)
        return Response("ok", status=200)

    dummy_handler = type("SlowHandler", (), {"__init__": lambda self, app: None, "handle": slow_handle})
    monkeypatch.setattr(app_module, "SlackRequestHandler", dummy_handler)
    flask_app = app_module.create_app()

    body = "{}"
    timestamp = "1700000000"
    monkeypatch.setattr(security, "time", SimpleNamespace(time=lambda: int(timestamp)))
    headers = _signed_headers("secret", body, timestamp)

    client = flask_app.test_client()
    response = client.post(
        "/slack/events",
        data=body,
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.data == b""

