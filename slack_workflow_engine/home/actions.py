"""Constants and builders for App Home interactive actions."""

from __future__ import annotations

import json
from typing import Literal

HOME_APPROVE_ACTION_ID = "home_workflow_approve"
HOME_REJECT_ACTION_ID = "home_workflow_reject"
HOME_DECISION_MODAL_CALLBACK_ID = "home_decision_submit"
HOME_REASON_BLOCK_ID = "reason_block"
HOME_REASON_ACTION_ID = "reason"
HOME_ATTACHMENT_BLOCK_ID = "attachment_block"
HOME_ATTACHMENT_ACTION_ID = "attachment_url"


def build_home_decision_modal(
    *,
    decision: Literal["APPROVED", "REJECTED"],
    request_id: int,
    workflow_type: str,
) -> dict:
    """Return a modal prompting the approver for decision context."""

    decision_label = "Approve" if decision == "APPROVED" else "Reject"
    require_reason = decision == "REJECTED"
    reason_label = "Rejection reason" if require_reason else "Approval note (optional)"

    metadata = json.dumps(
        {
            "request_id": request_id,
            "workflow_type": workflow_type,
            "decision": decision,
        }
    )

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Workflow:* `{workflow_type}` · *Request:* `#{request_id}`",
            },
        },
        {
            "type": "input",
            "block_id": HOME_REASON_BLOCK_ID,
            "label": {"type": "plain_text", "text": reason_label, "emoji": True},
            "optional": not require_reason,
            "element": {
                "type": "plain_text_input",
                "action_id": HOME_REASON_ACTION_ID,
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Add context for this decision"},
            },
        },
        {
            "type": "input",
            "block_id": HOME_ATTACHMENT_BLOCK_ID,
            "label": {"type": "plain_text", "text": "Attachment URL (optional)", "emoji": True},
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": HOME_ATTACHMENT_ACTION_ID,
                "placeholder": {"type": "plain_text", "text": "https://example.com/receipt.pdf"},
            },
        },
    ]

    return {
        "type": "modal",
        "callback_id": HOME_DECISION_MODAL_CALLBACK_ID,
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": f"{decision_label} Request", "emoji": True},
        "submit": {"type": "plain_text", "text": decision_label, "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": blocks,
    }
