"""Tests for publishing workflow request messages."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import Base, get_engine, get_session_factory  # noqa: E402
from slack_workflow_engine.models import Message  # noqa: E402
from slack_workflow_engine.workflows import (
    ApproverConfig,
    FieldDefinition,
    WorkflowDefinition,
)  # noqa: E402
from slack_workflow_engine.workflows.notifications import publish_request_message  # noqa: E402
from slack_workflow_engine.workflows.requests import canonical_json  # noqa: E402
from slack_workflow_engine.workflows.storage import save_request  # noqa: E402


@pytest.fixture(autouse=True)
def configure_database(monkeypatch, tmp_path):
    db_path = tmp_path / "notifications.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
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


class DummyWebClient:
    def __init__(self):
        self.calls = []
        self.response = {
            "ok": True,
            "channel": "CREFUND",
            "ts": "1700000000.123456",
            "message": {"thread_ts": "1700000000.123456"},
        }

    def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class DummyLogger:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, message, extra=None):
        self.errors.append((message, extra or {}))

    def warning(self, message, extra=None):
        self.warnings.append((message, extra or {}))


@pytest.fixture
def workflow_definition():
    return WorkflowDefinition(
        type="refund",
        title="Refund Request",
        fields=[
            FieldDefinition(name="order_id", label="Order ID", type="text", required=True),
            FieldDefinition(name="amount", label="Amount", type="number"),
        ],
        approvers=ApproverConfig(strategy="sequential", levels=[["U1"]]),
        notify_channel="CREFUND",
    )


def test_publish_request_message_saves_reference(workflow_definition):
    dummy_client = DummyWebClient()
    logger = DummyLogger()

    submission = {"order_id": "X-1"}
    request = save_request(
        workflow_type=workflow_definition.type,
        created_by="U123",
        payload_json=canonical_json(submission),
        request_key="key-123",
    )

    publish_request_message(
        client=dummy_client,
        definition=workflow_definition,
        submission=submission,
        request_id=request.id,
        logger=logger,
    )

    assert dummy_client.calls
    engine = get_engine()
    with engine.begin() as connection:
        rows = connection.execute(Message.__table__.select()).fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row.channel_id == "CREFUND"
        assert row.ts == "1700000000.123456"
        assert row.thread_ts == "1700000000.123456"
    assert not logger.errors


def test_publish_request_message_missing_identifiers(workflow_definition):
    dummy_client = DummyWebClient()
    dummy_client.response = {"ok": True}  # simulate unexpected response
    logger = DummyLogger()

    submission = {"order_id": "X-2"}
    request = save_request(
        workflow_type=workflow_definition.type,
        created_by="U123",
        payload_json=canonical_json(submission),
        request_key="key-456",
    )

    publish_request_message(
        client=dummy_client,
        definition=workflow_definition,
        submission=submission,
        request_id=request.id,
        logger=logger,
    )

    engine = get_engine()
    with engine.begin() as connection:
        rows = connection.execute(Message.__table__.select()).fetchall()
        assert not rows
    assert logger.warnings
