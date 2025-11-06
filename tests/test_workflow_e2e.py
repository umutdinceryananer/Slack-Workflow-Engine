"""Integration-style tests for request submission, approval, and rejection flows."""

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
from slack_workflow_engine.models import ApprovalDecision, Message, Request  # noqa: E402


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch, tmp_path):
    db_path = tmp_path / "e2e.db"
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    workflow = {
        "type": "refund",
        "title": "Refund",
        "fields": [
            {"name": "order_id", "label": "Order ID", "type": "text", "required": True},
            {"name": "amount", "label": "Amount", "type": "number"},
        ],
        "approvers": {"strategy": "sequential", "levels": [["U1", "U2"]]},
        "notify_channel": "CREFUND",
    }
    (workflows_dir / "refund.json").write_text(json.dumps(workflow), encoding="utf-8")

    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    monkeypatch.setattr(app_module, "WORKFLOW_DEFINITION_DIR", workflows_dir)

    engine = get_engine()
    Base.metadata.create_all(engine)

    yield

    Base.metadata.drop_all(engine)
    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


class DummySlackClient:
    def __init__(self):
        self.post_calls = []
        self.update_calls = []

    def chat_postMessage(self, **kwargs):
        self.post_calls.append(kwargs)
        return {
            "ok": True,
            "channel": kwargs["channel"],
            "ts": "1700000000.000100",
            "message": {"thread_ts": "1700000000.000100"},
        }

    def chat_update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"ok": True}


def test_submit_and_approve_flow(monkeypatch):
    bolt_logger = app_module._create_bolt_app(config.get_settings()).logger
    slack_client = DummySlackClient()

    def immediate_async(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_async", immediate_async)

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    body = {
        "user": {"id": "U123"},
        "view": {
            "private_metadata": json.dumps({"workflow_type": "refund"}),
            "state": {
                "values": {
                    "order_id": {"order_id": {"value": "INV-001"}},
                    "amount": {"amount": {"value": "50"}},
                }
            },
        },
    }

    app_module._handle_view_submission(
        ack=ack,
        body=body,
        client=slack_client,
        logger=bolt_logger,
    )

    assert ack_payloads == [{"response_action": "clear"}]
    assert slack_client.post_calls

    factory = get_session_factory()
    with factory() as session:
        request = session.query(Request).one()
        assert request.status == "PENDING"
        message = session.query(Message).one()
        action_body = {
            "user": {"id": "U1"},
            "actions": [
                {
                    "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
                }
            ],
        }

    ack_calls = []

    def ack_action(payload=None):
        ack_calls.append(payload)

    app_module._handle_approve_action(
        ack=ack_action,
        body=action_body,
        client=slack_client,
        logger=bolt_logger,
    )

    assert ack_calls == [{"response_type": "ephemeral", "text": "Request approved."}]
    assert slack_client.update_calls

    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "APPROVED"
        assert refreshed.decided_by == "U1"
        approval = session.query(ApprovalDecision).filter_by(request_id=request.id).one()
        assert approval.decision == "APPROVED"
        assert approval.reason is None
        assert approval.source == "channel"


def test_submit_and_reject_flow(monkeypatch):
    bolt_logger = app_module._create_bolt_app(config.get_settings()).logger
    slack_client = DummySlackClient()

    def immediate_async(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_async", immediate_async)

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    body = {
        "user": {"id": "U123"},
        "view": {
            "private_metadata": json.dumps({"workflow_type": "refund"}),
            "state": {
                "values": {
                    "order_id": {"order_id": {"value": "INV-002"}},
                    "amount": {"amount": {"value": "999"}},
                }
            },
        },
    }

    app_module._handle_view_submission(
        ack=ack,
        body=body,
        client=slack_client,
        logger=bolt_logger,
    )

    assert ack_payloads == [{"response_action": "clear"}]

    factory = get_session_factory()
    with factory() as session:
        request = session.query(Request).one()
        assert request.status == "PENDING"

    ack_calls = []

    def ack_action(payload=None):
        ack_calls.append(payload)

    rejection_body = {
        "user": {"id": "U2"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
        "state": {
            "values": {
                "reason_block": {"reason": {"value": "Budget exceeded"}},
            }
        },
    }

    app_module._handle_reject_action(
        ack=ack_action,
        body=rejection_body,
        client=slack_client,
        logger=bolt_logger,
    )

    assert ack_calls == [{"response_type": "ephemeral", "text": "Request rejected."}]
    assert slack_client.update_calls
    reason_payload = json.dumps(slack_client.update_calls[-1]["blocks"])
    assert "Budget exceeded" in reason_payload

    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "REJECTED"
        assert refreshed.decided_by == "U2"
        approval = session.query(ApprovalDecision).filter_by(request_id=request.id).one()
        assert approval.decision == "REJECTED"
        assert approval.reason == "Budget exceeded"
        assert approval.source == "channel"
