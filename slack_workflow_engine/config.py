"""Pydantic-based configuration helpers for Slack Workflow Engine."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable, List

from pydantic import BaseModel, Field, ValidationError, field_validator


class AppSettings(BaseModel):
    """Settings required to initialise the Slack bot and supporting services."""

    bot_token: str = Field(..., alias="SLACK_BOT_TOKEN")
    signing_secret: str = Field(..., alias="SLACK_SIGNING_SECRET")
    approver_user_ids: List[str] = Field(..., alias="APPROVER_USER_IDS")
    database_url: str = Field(..., alias="DATABASE_URL")
    home_recent_limit: int = Field(10, alias="HOME_RECENT_LIMIT")
    home_pending_limit: int = Field(10, alias="HOME_PENDING_LIMIT")

    @field_validator("approver_user_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [item.strip() for item in value if item.strip()]
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("home_recent_limit", "home_pending_limit")
    @classmethod
    def _ensure_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Home limits must be greater than zero")
        return value


def _format_missing(fields: Iterable[str]) -> str:
    """Return a human-friendly comma-separated list of missing env vars."""

    unique: List[str] = []
    for field in fields:
        if field not in unique:
            unique.append(field)
    return ", ".join(unique)


@lru_cache()
def get_settings() -> AppSettings:
    """Fetch and cache settings from environment variables."""

    try:
        return AppSettings.model_validate(os.environ)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        missing = [error["loc"][0] for error in exc.errors()]
        message = (
            "Missing required environment variables: "
            f"{_format_missing(missing)}"
        )
        raise RuntimeError(message) from exc
