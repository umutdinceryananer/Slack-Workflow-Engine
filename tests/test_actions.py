"""Tests for Slack action parsing and authorization helpers."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.actions import (  # noqa: E402
    ActionContext,
    is_user_authorized,
    parse_action_context,
)


def test_parse_action_context_valid_payload():
    context = parse_action_context('{"request_id": 10, "workflow_type": "refund"}')
    assert context == ActionContext(request_id=10, workflow_type="refund")


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '{"request_id": "abc", "workflow_type": "refund"}',
        '{"request_id": 3}',
        '["array"]',
    ],
)
def test_parse_action_context_invalid(payload):
    with pytest.raises(ValueError):
        parse_action_context(payload)


def test_is_user_authorized_true():
    allowed = ["U1", "U2", " U3 "]
    assert is_user_authorized("U3", allowed) is True


def test_is_user_authorized_false():
    allowed = ["U1", "U2"]
    assert is_user_authorized("U9", allowed) is False

