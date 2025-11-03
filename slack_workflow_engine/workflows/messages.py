"""Block Kit message builders for workflow requests."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .models import WorkflowDefinition

APPROVE_ACTION_ID = "workflow_approve"
REJECT_ACTION_ID = "workflow_reject"

_MISSING_VALUE = "_Not provided_"


def _format_field(label: str, value: Any) -> str:
    if value is None:
        return f"*{label}:* {_MISSING_VALUE}"

    if isinstance(value, str) and value.strip() == "":
        return f"*{label}:* {_MISSING_VALUE}"

    pretty_value = str(value)
    return f"*{label}:* {pretty_value}"


def _build_fields_section(definition: WorkflowDefinition, submission: Dict[str, Any]) -> Dict[str, Any]:
    lines: List[str] = []
    for field in definition.fields:
        value = submission.get(field.name)
        lines.append(_format_field(field.label, value))

    if not lines:
        lines.append(_MISSING_VALUE)

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(lines),
        },
    }


def _decision_buttons_payload(request_id: int, workflow_type: str, approver_level: int | None = None) -> Dict[str, Any]:
    payload_obj: Dict[str, Any] = {"request_id": request_id, "workflow_type": workflow_type}
    if approver_level is not None:
        payload_obj["level"] = approver_level
    payload = json.dumps(payload_obj, separators=(",", ":"))
    return {
        "type": "actions",
        "block_id": "workflow_decision_buttons",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                "style": "primary",
                "action_id": APPROVE_ACTION_ID,
                "value": payload,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reject", "emoji": True},
                "style": "danger",
                "action_id": REJECT_ACTION_ID,
                "value": payload,
                "confirm": {
                    "title": {"type": "plain_text", "text": "Reject request"},
                    "text": {
                        "type": "mrkdwn",
                        "text": "Are you sure you want to reject this request?",
                    },
                    "confirm": {"type": "plain_text", "text": "Reject"},
                    "deny": {"type": "plain_text", "text": "Cancel"},
                },
            },
        ],
    }


def build_request_message(
    *,
    definition: WorkflowDefinition,
    submission: Dict[str, Any],
    request_id: int,
    approver_level: int | None = None,
) -> Dict[str, Any]:
    """Build the canonical Slack message payload for a workflow request."""

    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": definition.title, "emoji": True},
        },
        _build_fields_section(definition, submission),
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"- Workflow: `{definition.type}` - Request ID: `{request_id}`",
                }
            ],
        },
        _decision_buttons_payload(request_id, definition.type, approver_level),
    ]

    return {
        "text": f"New {definition.title} request submitted.",
        "blocks": blocks,
    }


_DECISION_EMOJI = {
    "APPROVED": ":white_check_mark:",
    "REJECTED": ":no_entry_sign:",
}


def build_request_decision_update(
    *,
    definition: WorkflowDefinition,
    submission: Dict[str, Any],
    request_id: int,
    decision: str,
    decided_by: str,
) -> Dict[str, Any]:
    """Return an updated Slack message payload after a decision."""

    base = build_request_message(
        definition=definition,
        submission=submission,
        request_id=request_id,
    )
    blocks = list(base["blocks"][:-1])  # drop the action buttons

    emoji = _DECISION_EMOJI.get(decision.upper(), ":information_source:")
    decision_label = decision.capitalize()
    decision_block = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"{emoji} {decision_label} by <@{decided_by}>",
            }
        ],
    }
    blocks.append(decision_block)

    return {
        "text": f"{base['text']} {decision_label} by <@{decided_by}>.",
        "blocks": blocks,
    }
