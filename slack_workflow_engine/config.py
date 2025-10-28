"""Pydantic-based configuration helpers for Slack Workflow Engine."""

from functools import lru_cache
from typing import Iterable, List

import os
from pydantic import BaseModel, Field, ValidationError


class SlackSettings(BaseModel):
    """Settings required to initialise the Slack Bolt application."""

    bot_token: str = Field(..., alias="SLACK_BOT_TOKEN")
    signing_secret: str = Field(..., alias="SLACK_SIGNING_SECRET")


def _format_missing(fields: Iterable[str]) -> str:
    """Return a human friendly comma-separated list of missing env vars."""

    unique: List[str] = []
    for field in fields:
        if field not in unique:
            unique.append(field)
    return ", ".join(unique)


@lru_cache()
def get_settings() -> SlackSettings:
    """Fetch and cache Slack settings from environment variables."""

    try:
        return SlackSettings.model_validate(os.environ)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        missing = [
            "SLACK_BOT_TOKEN" if error["loc"][0] == "bot_token" else error["loc"][0]
            for error in exc.errors()
        ]
        message = (
            "Missing required environment variables: "
            f"{_format_missing(missing)}"
        )
        raise RuntimeError(message) from exc
