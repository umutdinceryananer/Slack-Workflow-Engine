"""Utilities for building Slack modals from workflow definitions."""

from __future__ import annotations

from typing import Dict, List

from .models import FieldDefinition, WorkflowDefinition

MAX_TITLE_LENGTH = 24
MAX_LABEL_LENGTH = 75


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _field_to_block(field: FieldDefinition) -> Dict:
    element: Dict[str, object] = {
        "type": "plain_text_input",
        "action_id": field.name,
        "placeholder": {"type": "plain_text", "text": "Enter a value"},
    }
    if field.type == "textarea":
        element["multiline"] = True
    elif field.type == "number":
        element["subtype"] = "number"

    block: Dict[str, object] = {
        "type": "input",
        "block_id": field.name,
        "label": {
            "type": "plain_text",
            "text": _truncate(field.label, MAX_LABEL_LENGTH),
            "emoji": True,
        },
        "element": element,
    }
    if not field.required:
        block["optional"] = True
    return block


def build_modal_view(definition: WorkflowDefinition) -> Dict:
    """Build a Slack modal payload for the supplied workflow definition."""

    blocks: List[Dict] = [_field_to_block(field) for field in definition.fields]

    return {
        "type": "modal",
        "callback_id": f"workflow_submit:{definition.type}",
        "title": {"type": "plain_text", "text": _truncate(definition.title, MAX_TITLE_LENGTH), "emoji": True},
        "submit": {"type": "plain_text", "text": "Submit", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": blocks,
    }
