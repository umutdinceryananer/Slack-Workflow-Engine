"""Builders for Slack App Home views."""

from __future__ import annotations

from datetime import UTC
from typing import Iterable, Sequence

from .data import RequestSummary


def _divider() -> dict:
    """Return a reusable divider block."""

    return {"type": "divider"}


def _section(text: str) -> dict:
    """Return a simple mrkdwn section block."""

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": text,
        },
    }


def _format_status(status: str) -> str:
    return status.replace("_", " ").title()


def _format_type(workflow_type: str) -> str:
    return workflow_type.replace("_", " ").title()


def _format_timestamp(value) -> str:
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _format_summary(summary: RequestSummary, *, include_decider: bool = False) -> str:
    parts = [
        f"*{_format_type(summary.workflow_type)}*",
        f"`#{summary.id}`",
        _format_status(summary.status),
        _format_timestamp(summary.created_at),
    ]

    if include_decider and summary.decided_by:
        parts.append(f"by <@{summary.decided_by}>")

    return " · ".join(parts)


def _build_list_section(title: str, items: Sequence[RequestSummary], *, empty_text: str, include_decider: bool = False) -> dict:
    if items:
        lines = "\n".join(f"• {_format_summary(item, include_decider=include_decider)}" for item in items)
    else:
        lines = empty_text

    return _section(f"*{title}*\n{lines}")


def build_home_view(
    *,
    my_requests: Sequence[RequestSummary] | Iterable[RequestSummary],
    pending_approvals: Sequence[RequestSummary] | Iterable[RequestSummary],
) -> dict:
    """Build the Home tab populated with data."""

    my_requests = list(my_requests)
    pending_approvals = list(pending_approvals)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Slack Workflow Engine",
                "emoji": True,
            },
        },
        _section(
            "Centralised request workflows in one place. Track progress, respond to approvals, "
            "and access quick actions from this Home tab."
        ),
        _divider(),
        _build_list_section(
            "My Requests",
            my_requests,
            empty_text="_No recent requests yet._",
        ),
        _divider(),
        _build_list_section(
            "Pending Approvals",
            pending_approvals,
            empty_text="_Nothing waiting on you right now._",
            include_decider=False,
        ),
    ]

    return {"type": "home", "blocks": blocks}


def build_home_placeholder_view() -> dict:
    """Fallback placeholder that mirrors the populated layout with empty data."""

    return build_home_view(my_requests=[], pending_approvals=[])
