"""Tests for the reject action handler."""

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
from slack_workflow_engine.models import Request  # noqa: E402
from slack_workflow_engine.workflows.requests import canonical_json  # noqa: E402
from slack_workflow_engine.workflows.storage import (  # noqa: E402
    save_message_reference,
    save_request,
)


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch, tmp_path):
    db_path = tmp_path / "reject_actions.db"
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


@pytest.fixture
def logger():
    bolt_app = app_module._create_bolt_app(config.get_settings())
    return bolt_app.logger


class DummySlackWebClient:
    def __init__(self):
        self.update_calls = []
        self.ephemeral_calls = []

    def chat_update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"ok": True}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral_calls.append(kwargs)
        return {"ok": True}

def _create_request_with_message():
    request = save_request(
        workflow_type="refund",
        created_by="U9",
        payload_json=canonical_json({"order_id": "R-1"}),
        request_key="reject-key-1",
    )
    save_message_reference(
        request_id=request.id,
        channel_id="CREFUND",
        ts="1700000000.222",
    )
    return request


def test_handle_reject_action_authorized(monkeypatch, logger):
    request = _create_request_with_message()
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()

    def immediate_async(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_async", immediate_async)

    body = {
        "user": {"id": "U2"},
        "channel": {"id": "CREFUND"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
        "state": {
            "values": {
                "reason_block": {
                    "reason": {"value": "Out of policy"},
                }
            }
        },
    }

    app_module._handle_reject_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads == [{"response_type": "ephemeral", "text": "Request rejected."}]
    assert slack_client.update_calls
    assert "Out of policy" in json.dumps(slack_client.update_calls[-1]["blocks"])

    factory = get_session_factory()
    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "REJECTED"
        assert refreshed.decided_by == "U2"


def test_handle_reject_action_unauthorized(monkeypatch, logger):
    request = _create_request_with_message()
    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    slack_client = DummySlackWebClient()
    monkeypatch.setattr(app_module, "run_async", lambda func, /, *args, **kwargs: func(*args, **kwargs))

    body = {
        "user": {"id": "U999"},
        "channel": {"id": "CREFUND"},
        "actions": [
            {
                "value": json.dumps({"request_id": request.id, "workflow_type": "refund"}),
            }
        ],
    }

    app_module._handle_reject_action(ack=ack, body=body, client=slack_client, logger=logger)

    assert ack_payloads == [None]
    assert not slack_client.update_calls
    assert slack_client.ephemeral_calls == [
        {"channel": "CREFUND", "user": "U999", "text": "You are not authorized to reject this request."}
    ]

    factory = get_session_factory()
    with factory() as session:
        refreshed = session.get(Request, request.id)
        assert refreshed.status == "PENDING"
