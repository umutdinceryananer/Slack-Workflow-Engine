"""Utilities for publishing workflow requests to Slack channels."""

from __future__ import annotations

from typing import Any, Mapping

from slack_sdk.errors import SlackApiError

from slack_workflow_engine.slack_client import SlackClient

from .messages import build_request_message
from .models import WorkflowDefinition
from .storage import save_message_reference


def publish_request_message(
    *,
    client,
    definition: WorkflowDefinition,
    submission: Mapping[str, Any],
    request_id: int,
    logger,
) -> None:
    """Post the workflow request message to Slack and store its reference."""

    slack_client = SlackClient(client=client)
    message_payload = build_request_message(
        definition=definition,
        submission=submission,
        request_id=request_id,
    )

    try:
        response = slack_client.post_message(
            channel=definition.notify_channel,
            text=message_payload["text"],
            blocks=message_payload["blocks"],
        )
    except SlackApiError as exc:  # pragma: no cover - depends on Slack API behaviour
        logger.error(
            "Failed to publish workflow request message",
            extra={"workflow_type": definition.type, "error": exc.response.get("error")},
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
