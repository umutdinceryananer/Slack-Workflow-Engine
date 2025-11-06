"""Tests for workflow request message builders."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.workflows import (  # noqa: E402
    WorkflowDefinition,
    build_request_message,
    build_request_decision_update,
    FieldDefinition,
    ApproverConfig,
    APPROVE_ACTION_ID,
    REJECT_ACTION_ID,
)


@pytest.fixture
def workflow_definition():
    return WorkflowDefinition(
        type="refund",
        title="Refund Request",
        fields=[
            FieldDefinition(name="order_id", label="Order ID", type="text", required=True),
            FieldDefinition(name="amount", label="Amount", type="number"),
        ],
        approvers=ApproverConfig(strategy="sequential", levels=[["U1"], ["U2"]]),
        notify_channel="CREFUND",
    )


def test_build_request_message_contains_buttons(workflow_definition):
    submission = {"order_id": "A-123", "amount": 42.5}

    message = build_request_message(definition=workflow_definition, submission=submission, request_id=99)

    assert message["text"].startswith("New Refund Request")
    blocks = message["blocks"]
    assert blocks[0]["type"] == "header"

    actions_block = blocks[-1]
    assert actions_block["type"] == "actions"
    approve_button, reject_button = actions_block["elements"]

    assert approve_button["action_id"] == APPROVE_ACTION_ID
    assert reject_button["action_id"] == REJECT_ACTION_ID

    payload = json.loads(approve_button["value"])
    assert payload == {"request_id": 99, "workflow_type": "refund"}


def test_missing_field_uses_placeholder(workflow_definition):
    submission = {"order_id": "B-456"}

    message = build_request_message(definition=workflow_definition, submission=submission, request_id=10)

    section_block = message["blocks"][1]
    text = section_block["text"]["text"]
    assert "*Order ID:* B-456" in text
    assert "*Amount:* _Not provided_" in text


def test_build_request_decision_update_replaces_buttons(workflow_definition):
    submission = {"order_id": "C-001", "amount": 10}

    updated = build_request_decision_update(
        definition=workflow_definition,
        submission=submission,
        request_id=77,
        decision="APPROVED",
        decided_by="U777",
    )

    blocks = updated["blocks"]
    assert blocks[-1]["type"] == "context"
    context_text = blocks[-1]["elements"][0]["text"]
    assert "Approved" in context_text
    assert "U777" in context_text
    assert all(block.get("type") != "actions" for block in blocks)


def test_build_request_decision_update_includes_reason(workflow_definition):
    submission = {"order_id": "D-100"}



    updated = build_request_decision_update(
        definition=workflow_definition,
        submission=submission,
        request_id=5,
        decision="REJECTED",
        decided_by="U9",
        reason="Missing receipt",
    )

    reason_block = updated["blocks"][-1]
    assert reason_block["type"] == "section"
    assert "Missing receipt" in reason_block["text"]["text"]



def test_build_request_decision_update_includes_attachment_url(workflow_definition):
    submission = {"order_id": "E-500"}

    updated = build_request_decision_update(
        definition=workflow_definition,
        submission=submission,
        request_id=6,
        decision="APPROVED",
        decided_by="U42",
        attachment_url="https://example.com/receipt.pdf",
    )

    attachment_block = updated["blocks"][-1]
    assert attachment_block["type"] == "section"
    assert "https://example.com/receipt.pdf" in attachment_block["text"]["text"]
