"""Utilities for handling Slack interaction payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ActionContext:
    """Parsed context describing a workflow action invocation."""

    request_id: int
    workflow_type: str
    level: int | None = None


def parse_action_context(raw_value: str) -> ActionContext:
    """Parse the action value into a structured context."""

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid action payload.") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid action payload.")

    request_id = payload.get("request_id")
    workflow_type = payload.get("workflow_type")

    if not isinstance(request_id, int):
        raise ValueError("Invalid action payload.")
    if not isinstance(workflow_type, str) or not workflow_type:
        raise ValueError("Invalid action payload.")

    level = payload.get("level")
    if level is not None and not isinstance(level, int):
        raise ValueError("Invalid action payload.")

    return ActionContext(request_id=request_id, workflow_type=workflow_type, level=level)


def is_user_authorized(user_id: str, allowed_ids: Iterable[str]) -> bool:
    """Return True when the user is in the configured allow list."""

    normalized = {item.strip() for item in allowed_ids if item}
    return user_id in normalized
