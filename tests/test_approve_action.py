"""Tests for the approve action handler."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import Base, get_engine, get_session_factory  # noqa: E402
from slack_workflow_engine.models import ApprovalDecision, Request  # noqa: E402
from slack_workflow_engine.workflows.requests import canonical_json  # noqa: E402
from slack_workflow_engine.workflows.storage import (
    save_message_reference,
    save_request,
)  # noqa: E402


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch, tmp_path):
    db_path = tmp_path / "actions.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U123,U456")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    config.get_settings.cache_clear()
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
        self.update_calls = []
        self.ephemeral_calls = []
        self.publish_calls = []

    def chat_update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"ok": True}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral_calls.append(kwargs)
        return {"ok": True}

    def views_publish(self, **kwargs):
        self.publish_calls.append(kwargs)
        return {"ok": True}

def _run_async_sync(func, /, *args, **kwargs):
    """Execute run_async workloads synchronously while ignoring trace context metadata."""

    kwargs.pop("trace_id", None)
    return func(*args, **kwargs)


def _create_request_with_message():
    submission = {"order_id": "12345"}
    request = save_request(
        workflow_type="refund",
        created_by="U222",
        payload_json=canonical_json(submission),
        request_key="key-approve",
    )
    save_message_reference(
        request_id=request.id,
        channel_id="CREFUND",
        ts="1700000000.555",
    )
    return request


def test_handle_approve_action_authorized(monkeypatch, logger):
    request = _create_request_with_message()
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()

    monkeypatch.setattr(app_module, "run_async", _run_async_sync)

    body = {
        "user": {"id": "U123"},
        "channel": {"id": "CREFUND"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
    }

    app_module._handle_approve_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads == [{"response_type": "ephemeral", "text": "Request approved."}]
    assert slack_client.update_calls
    publish_targets = {call["user_id"] for call in slack_client.publish_calls}
    assert publish_targets == {"U123", "U222"}

    factory = get_session_factory()
    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "APPROVED"
        assert refreshed.decided_by == "U123"
        approval = session.query(ApprovalDecision).filter_by(request_id=request.id).one()
        assert approval.decision == "APPROVED"
        assert approval.reason is None
        assert approval.source == "channel"


def test_handle_approve_action_unauthorized(monkeypatch, logger):
    request = _create_request_with_message()
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()
    monkeypatch.setattr(app_module, "run_async", _run_async_sync)

    body = {
        "user": {"id": "U999"},
        "channel": {"id": "CREFUND"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
    }

    app_module._handle_approve_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads == [None]
    assert not slack_client.update_calls
    assert not slack_client.publish_calls
    assert slack_client.ephemeral_calls == [
        {"channel": "CREFUND", "user": "U999", "text": "You are not authorized to approve this request."}
    ]

    factory = get_session_factory()
    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "PENDING"
        assert session.query(ApprovalDecision).count() == 0


def test_handle_approve_action_self_guard(monkeypatch, logger):
    monkeypatch.setenv("APPROVER_USER_IDS", "U123,U456,U333")
    config.get_settings.cache_clear()

    submission = {"order_id": "SELF-1"}
    request = save_request(
        workflow_type="refund",
        created_by="U333",
        payload_json=canonical_json(submission),
        request_key="key-self",
    )
    save_message_reference(
        request_id=request.id,
        channel_id="CSELF",
        ts="1700000000.777",
    )

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()
    monkeypatch.setattr(app_module, "run_async", _run_async_sync)

    body = {
        "user": {"id": "U333"},
        "channel": {"id": "CSELF"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
    }

    app_module._handle_approve_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads == [None]
    assert not slack_client.update_calls
    assert not slack_client.publish_calls
    assert slack_client.ephemeral_calls == [
        {"channel": "CSELF", "user": "U333", "text": "You cannot approve your own request."}
    ]

    factory = get_session_factory()
    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "PENDING"
        assert session.query(ApprovalDecision).count() == 0


def test_handle_approve_action_duplicate_click(monkeypatch, logger):
    request = _create_request_with_message()

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()
    monkeypatch.setattr(app_module, "run_async", _run_async_sync)

    body = {
        "user": {"id": "U123"},
        "channel": {"id": "CREFUND"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
    }

    app_module._handle_approve_action(ack=ack, body=body, client=slack_client, logger=logger)
    app_module._handle_approve_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads[0] == {"response_type": "ephemeral", "text": "Request approved."}
    assert ack_payloads[1] is None
    assert len(slack_client.update_calls) == 1
    assert slack_client.update_calls[0]["channel"] == "CREFUND"
    assert slack_client.ephemeral_calls[-1] == {
        "channel": "CREFUND",
        "user": "U123",
        "text": "This request has already been decided.",
    }
    publish_targets = {call["user_id"] for call in slack_client.publish_calls}
    assert publish_targets == {"U123", "U222"}

    factory = get_session_factory()
    with factory() as session:
        approvals = session.query(ApprovalDecision).filter_by(request_id=request.id).all()
        assert len(approvals) == 1
