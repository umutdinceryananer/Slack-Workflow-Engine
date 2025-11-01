"""Utilities for parsing and canonicalising workflow request submissions."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from .models import FieldDefinition, WorkflowDefinition


class SubmissionValue(BaseModel):
    """Represents a single field value coming from Slack modal state."""

    value: str | None = Field(None, alias="value")


class SubmissionState(BaseModel):
    """Model to validate Slack modal state payloads."""

    values: Dict[str, Dict[str, SubmissionValue]]


def _normalise_field_value(raw: str | None, field: FieldDefinition) -> Any:
    if raw is None:
        return None
    if field.type == "number":
        try:
            return float(raw)
        except ValueError:
            return raw  # will be handled by higher-level validation later
    return raw.strip()


def parse_submission(state_payload: Dict[str, Any], definition: WorkflowDefinition) -> Dict[str, Any]:
    """Parse and canonicalise a Slack modal submission."""

    try:
        state = SubmissionState.model_validate(state_payload)
    except ValidationError as exc:
        raise ValueError("Invalid submission payload") from exc

    submission: Dict[str, Any] = {}
    for field in definition.fields:
        field_state = state.values.get(field.name, {})
        # Slack uses action id inside each block; we expect it to match field.name
        submission_value = None
        if field.name in field_state:
            submission_value = field_state[field.name].value
        else:
            # take the first value if keys don't match for some reason
            submission_value = next(iter(field_state.values()), SubmissionValue()).value

        normalised = _normalise_field_value(submission_value, field)
        if field.required and (normalised is None or (isinstance(normalised, str) and normalised.strip() == "")):
            raise ValueError(f"Field '{field.label}' is required.")
        submission[field.name] = normalised

    return submission


def canonical_json(data: Dict[str, Any]) -> str:
    """Return a canonical JSON string with stable ordering and whitespace."""

    return json.dumps(data, sort_keys=True, separators=(",", ":"))
