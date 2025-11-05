"""Builders for Slack App Home views."""

from __future__ import annotations

from datetime import UTC
from typing import Iterable, Sequence

from .actions import HOME_APPROVE_ACTION_ID, HOME_REJECT_ACTION_ID
from .data import RequestSummary
from .filters import HomeFilters, PaginationState


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


def _format_filter_group(label: str, items: list[str] | None) -> str:
    if not items:
        return f"{label}: _All_"
    return f"{label}: {', '.join(sorted(items))}"


def _format_sort_label(sort_by: str, sort_order: str) -> str:
    field_labels = {
        "created_at": "Created",
        "status": "Status",
        "type": "Workflow",
    }
    order_label = "Descending" if sort_order.lower() == "desc" else "Ascending"
    return f"Sort: {field_labels.get(sort_by, 'Created')} ({order_label})"


def _filters_section(my_filters: HomeFilters, pending_filters: HomeFilters) -> dict:
    summary_lines = [
        "*Filters*",
        f"*My Requests*: {_format_filter_group('Type', my_filters.workflow_types)} | "
        f"{_format_filter_group('Status', my_filters.statuses)} | {_format_sort_label(my_filters.sort_by, my_filters.sort_order)}",
        f"*Pending Approvals*: {_format_filter_group('Type', pending_filters.workflow_types)} | "
        f"{_format_filter_group('Status', pending_filters.statuses)} | {_format_sort_label(pending_filters.sort_by, pending_filters.sort_order)}",
    ]
    return _section("\n".join(summary_lines))


def _pagination_blocks(title: str, prefix: str, pagination: PaginationState) -> list[dict]:
    elements = []
    prev_value = max(pagination.offset - pagination.limit, 0)
    next_value = pagination.offset + pagination.limit

    elements.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Previous"},
            "action_id": f"{prefix}_prev",
            "value": str(prev_value),
            "style": "primary",
            "disabled": not pagination.has_previous,
        }
    )
    elements.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Next"},
            "action_id": f"{prefix}_next",
            "value": str(next_value),
            "style": "primary",
            "disabled": not pagination.has_more,
        }
    )

    start = pagination.offset + 1 if pagination.has_previous or pagination.offset > 0 else (1 if pagination.has_more else 0)
    end = pagination.offset + pagination.limit if pagination.has_more or pagination.has_previous else max(pagination.limit, 0)

    context_block = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"*{title}* · Showing {start}–{end}",
            }
        ],
    }

    actions_block = {"type": "actions", "elements": elements}
    return [context_block, actions_block]


def _decision_payload(summary: RequestSummary) -> str:
    import json

    payload = json.dumps({"request_id": summary.id, "workflow_type": summary.workflow_type})
    return payload


def _pending_action_blocks(pending: Sequence[RequestSummary]) -> list[dict]:
    blocks: list[dict] = []
    for summary in pending:
        blocks.append(
            {
                "type": "actions",
                "block_id": f"home_pending_actions_{summary.id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                        "style": "primary",
                        "action_id": HOME_APPROVE_ACTION_ID,
                        "value": _decision_payload(summary),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject", "emoji": True},
                        "style": "danger",
                        "action_id": HOME_REJECT_ACTION_ID,
                        "value": _decision_payload(summary),
                    },
                ],
            }
        )
    return blocks


def build_home_view(
    *,
    my_requests: Sequence[RequestSummary] | Iterable[RequestSummary],
    pending_approvals: Sequence[RequestSummary] | Iterable[RequestSummary],
    my_filters: HomeFilters,
    pending_filters: HomeFilters,
    my_pagination: PaginationState,
    pending_pagination: PaginationState,
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
        _filters_section(my_filters, pending_filters),
        _divider(),
        _build_list_section(
            "My Requests",
            my_requests,
            empty_text="_No recent requests yet._",
        ),
    ]

    blocks.extend(_pagination_blocks("My Requests", "my_requests", my_pagination))

    blocks.append(_divider())

    blocks.append(
        _build_list_section(
            "Pending Approvals",
            pending_approvals,
            empty_text="_Nothing waiting on you right now._",
            include_decider=False,
        )
    )

    if pending_approvals:
        blocks.extend(_pending_action_blocks(pending_approvals))

    blocks.extend(_pagination_blocks("Pending Approvals", "pending", pending_pagination))

    return {"type": "home", "blocks": blocks}


def build_home_placeholder_view() -> dict:
    """Fallback placeholder that mirrors the populated layout with empty data."""
    default_filters = HomeFilters(None, None, None, None, "created_at", "desc", 10, 0)
    pending_filters = HomeFilters(None, ["PENDING"], None, None, "created_at", "asc", 10, 0)
    default_pagination = PaginationState()
    return build_home_view(
        my_requests=[],
        pending_approvals=[],
        my_filters=default_filters,
        pending_filters=pending_filters,
        my_pagination=default_pagination,
        pending_pagination=default_pagination,
    )
