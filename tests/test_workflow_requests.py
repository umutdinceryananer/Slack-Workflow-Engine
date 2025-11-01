"""Tests for workflow submission parsing and canonicalisation."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.workflows.models import WorkflowDefinition  # noqa: E402
from slack_workflow_engine.workflows.requests import (  # noqa: E402
    canonical_json,
    parse_submission,
)


@pytest.fixture
def workflow_definition():
    return WorkflowDefinition(
        type="demo",
        title="Demo",
        fields=[
            {"name": "order_id", "label": "Order", "type": "text", "required": True},
            {"name": "amount", "label": "Amount", "type": "number", "required": True},
            {"name": "note", "label": "Note", "type": "textarea"},
        ],
        approvers={"strategy": "sequential", "levels": [["U1"]]},
        notify_channel="C123",
    )


def test_parse_submission_normalises_values(workflow_definition):
    state = {
        "values": {
            "order_id": {"order_id": {"value": " 12345 "}},
            "amount": {"amount": {"value": "42.50"}},
            "note": {"note": {"value": "  Hello world  "}},
        }
    }

    parsed = parse_submission(state, workflow_definition)

    assert parsed["order_id"] == "12345"
    assert parsed["amount"] == 42.50
    assert parsed["note"] == "Hello world"


def test_parse_submission_missing_required_field(workflow_definition):
    state = {"values": {"amount": {"amount": {"value": "100"}}}}

    with pytest.raises(ValueError):
        parse_submission(state, workflow_definition)


def test_canonical_json_stable_ordering():
    data = {"b": 2, "a": 1}
    encoded = canonical_json(data)
    decoded = json.loads(encoded)

    assert encoded == '{"a":1,"b":2}'
    assert decoded == {"a": 1, "b": 2}
