"""Pydantic models describing workflow definitions."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator

_ALLOWED_FIELD_TYPES = {"text", "number", "textarea"}


class FieldDefinition(BaseModel):
    name: str
    label: str
    type: str = Field(..., description="Field type: text, number, textarea")
    required: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in _ALLOWED_FIELD_TYPES:
            raise ValueError(f"Unsupported field type '{value}'")
        return value


class ApproverConfig(BaseModel):
    strategy: str = Field("sequential", description="Approval strategy: sequential or parallel")
    levels: List[List[str]]

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_structure(cls, value):
        """Support legacy config where approvers were provided as a flat list."""

        if isinstance(value, list):
            return {"strategy": "sequential", "levels": [value]}

        if isinstance(value, dict):
            if "levels" not in value and "members" in value:
                members = value.get("members")
                value = value.copy()
                value.pop("members", None)
                value["levels"] = [members]
            return value

        return value

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        if value not in {"sequential", "parallel"}:
            raise ValueError("strategy must be 'sequential' or 'parallel'")
        return value

    @field_validator("levels")
    @classmethod
    def validate_levels(cls, value: List[List[str]]) -> List[List[str]]:
        if not value:
            raise ValueError("levels must contain at least one approval level")

        normalised_levels: List[List[str]] = []
        for level in value:
            if not level:
                raise ValueError("each approval level must include at least one approver id")

            cleaned_level: List[str] = []
            seen: set[str] = set()
            for approver in level:
                member = (approver or "").strip()
                if not member:
                    raise ValueError("approver ids must be non-empty strings")
                if member in seen:
                    raise ValueError("approver ids within a level must be unique")
                seen.add(member)
                cleaned_level.append(member)

            normalised_levels.append(cleaned_level)

        return normalised_levels


class WorkflowDefinition(BaseModel):
    type: str
    title: str
    fields: List[FieldDefinition]
    approvers: ApproverConfig
    notify_channel: str
