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


class ApproverLevel(BaseModel):
    members: List[str]
    quorum: int | None = None
    tie_breaker: str | None = None

    @model_validator(mode="before")
    @classmethod
    def coerce_members(cls, value):
        if isinstance(value, list):
            return {"members": value}
        return value

    @field_validator("members")
    @classmethod
    def validate_members(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("each approval level must include at least one approver id")

        cleaned: List[str] = []
        seen: set[str] = set()
        for approver in value:
            member = (approver or "").strip()
            if not member:
                raise ValueError("approver ids must be non-empty strings")
            if member in seen:
                raise ValueError("approver ids within a level must be unique")
            cleaned.append(member)
            seen.add(member)

        return cleaned

    @field_validator("tie_breaker")
    @classmethod
    def validate_tie_breaker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def ensure_quorum(self):
        total = len(self.members)
        if total == 0:
            return self

        if self.quorum is None:
            self.quorum = total
            return self

        if self.quorum < 1 or self.quorum > total:
            raise ValueError("quorum must be between 1 and the number of members in the level")
        return self


class ApproverConfig(BaseModel):
    strategy: str = Field("sequential", description="Approval strategy: sequential or parallel")
    levels: List[ApproverLevel]

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_structure(cls, value):
        """Support legacy config where approvers were provided as a flat list."""

        if isinstance(value, list):
            return {"strategy": "sequential", "levels": [{"members": value}]}

        if isinstance(value, dict):
            if "levels" not in value and "members" in value:
                members = value.get("members")
                value = value.copy()
                value.pop("members", None)
                value["levels"] = [{"members": members}]
            elif "levels" in value:
                transformed: List[dict] = []
                for level in value.get("levels") or []:
                    if isinstance(level, list):
                        transformed.append({"members": level})
                    else:
                        transformed.append(level)
                value = value.copy()
                value["levels"] = transformed
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
    def validate_levels(cls, value: List[ApproverLevel]) -> List[ApproverLevel]:
        if not value:
            raise ValueError("levels must contain at least one approval level")

        return value


class WorkflowDefinition(BaseModel):
    type: str
    title: str
    fields: List[FieldDefinition]
    approvers: ApproverConfig
    notify_channel: str
