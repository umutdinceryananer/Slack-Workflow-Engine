"""Tests for view submission handling."""

import json
import logging
from pathlib import Path
import sys

import pytest
import structlog
from structlog.contextvars import clear_contextvars
from structlog.testing import capture_logs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import get_engine, get_session_factory  # noqa: E402
from slack_workflow_engine.models import Base, Request, Message  # noqa: E402
from slack_workflow_engine.workflows.commands import load_workflow_or_raise  # noqa: E402
from slack_workflow_engine.workflows.requests import canonical_json, compute_request_key, parse_submission  # noqa: E402
from slack_workflow_engine.workflows.storage import save_request  # noqa: E402


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


class DummySlackWebClient:
    def __init__(self):
        self.calls = []

    def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "channel": kwargs["channel"],
            "ts": "1700000000.000001",
            "message": {"thread_ts": "1700000000.000001"},
        }


def run_async_sync(func, /, *args, **kwargs):
    """Execute asynchronous workloads immediately for tests while dropping trace metadata."""

    kwargs.pop("trace_id", None)
    return func(*args, **kwargs)


def test_handle_view_submission_persists_request(logger, monkeypatch):
    ack_calls = []

    def ack(payload=None):
        ack_calls.append(payload)

    slack_client = DummySlackWebClient()
    scheduled = []

    def fake_run_async(func, /, *args, **kwargs):
        trace_id = kwargs.pop("trace_id", None)
        scheduled.append((func, args, kwargs, trace_id))
        func(*args, **kwargs)
        return None

    monkeypatch.setattr(app_module, "run_async", fake_run_async)

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

    app_module._handle_view_submission(
        ack=ack,
        body=body,
        client=slack_client,
        logger=logger,
    )

    assert ack_calls == [{"response_action": "clear"}]
    assert scheduled
    func, args, kwargs, trace_id = scheduled[0]
    assert func is app_module.publish_request_message
    assert "request_id" in kwargs
    assert kwargs["definition"].type == "refund"
    assert trace_id

    engine = get_engine()
    with engine.begin() as connection:
        rows = connection.execute(Request.__table__.select()).fetchall()
        assert len(rows) == 1
        payload = json.loads(rows[0].payload_json)
        assert payload["order_id"] == "12345"
        assert payload["amount"] == 42.5
        messages = connection.execute(Message.__table__.select()).fetchall()
        assert len(messages) == 1
        expected_channel = kwargs["definition"].notify_channel
        assert messages[0].channel_id == expected_channel
        assert slack_client.calls[0]["channel"] == expected_channel


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

    app_module._handle_view_submission(ack=ack, body=body, client=object(), logger=logger)

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

    app_module._handle_view_submission(ack=ack, body=body, client=object(), logger=logger)

    assert ack_payloads[0]["errors"]["general"] == "Invalid workflow metadata."


def test_handle_view_submission_duplicate_request(logger, monkeypatch):
    ack_calls = []

    def ack(payload=None):
        ack_calls.append(payload)

    slack_client = DummySlackWebClient()
    monkeypatch.setattr(app_module, "run_async", run_async_sync)

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

    definition = load_workflow_or_raise("refund")
    state_payload = {"values": body["view"]["state"]["values"]}
    parsed_submission = parse_submission(state_payload, definition)
    payload = canonical_json(parsed_submission)
    request_key = compute_request_key("refund", "U123", payload)
    save_request(
        workflow_type="refund",
        created_by="U123",
        payload_json=payload,
        request_key=request_key,
    )
    engine = get_engine()
    with engine.begin() as connection:
        stored = connection.execute(Request.__table__.select()).fetchone()
        assert stored.request_key == request_key

    app_module._handle_view_submission(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_calls == [
        {"response_action": "errors", "errors": {"order_id": "You already submitted this request."}}
    ]

    with engine.begin() as connection:
        rows = connection.execute(Request.__table__.select()).fetchall()
        assert len(rows) == 1
        messages = connection.execute(Message.__table__.select()).fetchall()
        assert not messages


def test_request_created_log_contains_trace_id_without_payload(logger, monkeypatch):
    ack_calls = []

    def ack(payload=None):
        ack_calls.append(payload)

    clear_contextvars()
    monkeypatch.setattr(app_module, "run_async", lambda func, /, *args, **kwargs: None)

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

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        app_module._handle_view_submission(
            ack=ack,
            body=body,
            client=object(),
            logger=logger,
        )

    clear_contextvars()

    events = [entry for entry in logs if entry.get("event") == "request_created"]
    assert events, "request_created log line was not emitted"

    event = events[0]
    assert event.get("trace_id"), "trace_id missing from structured log"
    assert "request_id" in event, "request_id missing from structured log"
    assert "payload" not in event, "payload should not be logged"
    assert "payload_json" not in event, "payload_json should not be logged"
    assert ack_calls == [{"response_action": "clear"}]
