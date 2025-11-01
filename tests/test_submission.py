"""Tests for view submission handling."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import get_engine, get_session_factory  # noqa: E402
from slack_workflow_engine.models import Base, Request  # noqa: E402


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch, tmp_path):
    db_path = tmp_path / "requests.db"
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    workflow = {
        "type": "refund",
        "title": "Refund",
        "fields": [
            {"name": "order_id", "label": "Order ID", "type": "text", "required": True},
            {"name": "amount", "label": "Amount", "type": "number", "required": True},
        ],
        "approvers": {"strategy": "sequential", "levels": [["U1"]]},
        "notify_channel": "CREFUND",
    }
    (workflows_dir / "refund.json").write_text(json.dumps(workflow), encoding="utf-8")

    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    config.get_settings.cache_clear()
    monkeypatch.setattr(app_module, "WORKFLOW_DEFINITION_DIR", workflows_dir)
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(engine)

    yield

    Base.metadata.drop_all(engine)
    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def logger():
    bolt_app = app_module._create_bolt_app(config.get_settings())
    return bolt_app.logger


def test_handle_view_submission_persists_request(logger):
    ack_calls = []

    def ack(payload=None):
        ack_calls.append(payload)

    body = {
        "user": {"id": "U123"},
        "view": {
            "private_metadata": json.dumps({"workflow_type": "refund"}),
            "state": {
                "values": {
                    "order_id": {"order_id": {"value": "12345"}},
                    "amount": {"amount": {"value": "42.5"}},
                }
            },
        },
    }

    app_module._handle_view_submission(ack=ack, body=body, logger=logger)

    assert ack_calls == [{"response_action": "clear"}]

    engine = get_engine()
    with engine.begin() as connection:
        rows = connection.execute(Request.__table__.select()).fetchall()
        assert len(rows) == 1
        payload = json.loads(rows[0].payload_json)
        assert payload["order_id"] == "12345"
        assert payload["amount"] == 42.5


def test_handle_view_submission_missing_required(logger):
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    body = {
        "user": {"id": "U123"},
        "view": {
            "private_metadata": json.dumps({"workflow_type": "refund"}),
            "state": {"values": {"amount": {"amount": {"value": "10"}}}},
        },
    }

    app_module._handle_view_submission(ack=ack, body=body, logger=logger)

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert "order_id" in errors


def test_handle_view_submission_invalid_metadata(logger):
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    body = {
        "user": {"id": "U123"},
        "view": {
            "private_metadata": "not-json",
            "state": {"values": {}},
        },
    }

    app_module._handle_view_submission(ack=ack, body=body, logger=logger)

    assert ack_payloads[0]["errors"]["general"] == "Invalid workflow metadata."
