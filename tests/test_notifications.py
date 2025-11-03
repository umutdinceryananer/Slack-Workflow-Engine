"""Tests for Slack notification helpers."""

from __future__ import annotations

import logging

from slack_sdk.errors import SlackApiError
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.testing import capture_logs

from slack_workflow_engine.workflows import notifications
from slack_workflow_engine.workflows.models import (
    ApproverConfig,
    FieldDefinition,
    WorkflowDefinition,
)


class DummyResponse(dict):
    """Minimal Slack response stub for error handling tests."""

    def __init__(self, error: str = "invalid_arguments", status_code: int = 400) -> None:
        super().__init__({"error": error})
        self.status_code = status_code

    @property
    def data(self) -> dict[str, str]:
        return dict(self)

    def __repr__(self) -> str:
        return f"DummyResponse(error={self['error']!r}, status_code={self.status_code})"


def test_publish_request_message_logs_webhook_failure(monkeypatch):
    clear_contextvars()
    bind_contextvars(trace_id="trace-xyz")

    def failing_post_message(self, *, channel, text, blocks):
        raise SlackApiError("webhook error", DummyResponse())

    monkeypatch.setattr(notifications.SlackClient, "post_message", failing_post_message)

    definition = WorkflowDefinition(
        type="refund",
        title="Refund",
        fields=[FieldDefinition(name="amount", label="Amount", type="number", required=True)],
        approvers=ApproverConfig(levels=[["U1"]]),
        notify_channel="C123",
    )

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        notifications.publish_request_message(
            client=object(),
            definition=definition,
            submission={"amount": "10"},
            request_id=42,
            logger=logging.getLogger(__name__),
        )

    clear_contextvars()

    events = [entry for entry in logs if entry.get("event") == "webhook_failed"]
    assert events, "webhook_failed log was not emitted"

    event = events[0]
    assert event.get("trace_id") == "trace-xyz"
    assert event.get("request_id") == 42
    assert event.get("operation") == "publish_request_message"
    assert event.get("channel") == "C123"
    assert event.get("error") == "invalid_arguments"
