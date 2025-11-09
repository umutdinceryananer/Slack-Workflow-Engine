"""Utilities for publishing workflow requests to Slack channels."""

from __future__ import annotations

from typing import Any, Mapping

from slack_sdk.errors import SlackApiError
import structlog

from slack_workflow_engine.slack_client import SlackClient

from .messages import build_request_message, build_request_decision_update
from .models import WorkflowDefinition
from .storage import save_message_reference


def publish_request_message(
    *,
    client,
    definition: WorkflowDefinition,
    submission: Mapping[str, Any],
    request_id: int,
    logger,
    trace_id: str | None = None,
    approver_level: int | None = None,
    status_text: str | None = None,
) -> None:
    """Post the workflow request message to Slack and store its reference."""

    slack_client = SlackClient(client=client)
    log = structlog.get_logger().bind(
        request_id=request_id,
        workflow_type=definition.type,
        channel=definition.notify_channel,
    )
    message_payload = build_request_message(
        definition=definition,
        submission=submission,
        request_id=request_id,
        approver_level=approver_level,
        status_text=status_text,
    )

    try:
        response = slack_client.post_message(
            channel=definition.notify_channel,
            text=message_payload["text"],
            blocks=message_payload["blocks"],
        )
    except SlackApiError as exc:  # pragma: no cover - depends on Slack API behaviour
        status_code = getattr(exc.response, "status_code", None) if getattr(exc, "response", None) else None
        error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)
        log.error(
            "webhook_failed",
            operation="publish_request_message",
            error=error_code,
            status_code=status_code,
        )
        logger.error(
            "Failed to publish workflow request message",
            extra={
                "workflow_type": definition.type,
                "channel": definition.notify_channel,
                "error": exc.response.get("error"),
                "response": getattr(exc.response, "data", {}),
            },
        )
        return

    channel_id = response.get("channel")
    ts = response.get("ts")
    thread_ts = response.get("message", {}).get("thread_ts") if response.get("message") else None

    if not channel_id or not ts:
        logger.warning(
            "Slack response missing identifiers; skipping message reference persistence",
            extra={
                "workflow_type": definition.type,
                "response_keys": list(response.keys()),
            },
        )
        return

    save_message_reference(
        request_id=request_id,
        channel_id=channel_id,
        ts=ts,
        thread_ts=thread_ts,
    )


def update_request_message(
    *,
    client,
    definition: WorkflowDefinition,
    submission: Mapping[str, Any],
    request_id: int,
    decided_by: str,
    channel_id: str,
    ts: str,
    logger,
    decision: str | None = None,
    reason: str | None = None,
    attachment_url: str | None = None,
    status_text: str | None = None,
    approver_level: int | None = None,
    include_actions: bool | None = None,
    trace_id: str | None = None,
) -> None:
    """Update an existing Slack message to reflect the latest decision."""

    slack_client = SlackClient(client=client)
    log = structlog.get_logger().bind(
        request_id=request_id,
        workflow_type=definition.type,
        channel=channel_id,
    )
    if decision:
        payload = build_request_decision_update(
            definition=definition,
            submission=submission,
            request_id=request_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
            attachment_url=attachment_url,
            status_text=status_text,
        )
    else:
        payload = build_request_message(
            definition=definition,
            submission=submission,
            request_id=request_id,
            approver_level=approver_level,
            status_text=status_text,
            include_actions=True if include_actions is None else include_actions,
        )

    try:
        slack_client.update_message(
            channel=channel_id,
            ts=ts,
            text=payload["text"],
            blocks=payload["blocks"],
        )
    except SlackApiError as exc:  # pragma: no cover - depends on Slack API behaviour
        status_code = getattr(exc.response, "status_code", None) if getattr(exc, "response", None) else None
        error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)
        log.error(
            "webhook_failed",
            operation="update_request_message",
            error=error_code,
            status_code=status_code,
        )
        logger.error(
            "Failed to update workflow request message",
            extra={
                "workflow_type": definition.type,
                "request_id": request_id,
                "error": exc.response.get("error"),
            },
        )
