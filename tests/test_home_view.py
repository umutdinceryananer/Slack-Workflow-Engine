from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.home import (  # noqa: E402
    PaginationState,
    RequestSummary,
    build_home_placeholder_view,
    build_home_view,
    HOME_APPROVE_ACTION_ID,
    HOME_REJECT_ACTION_ID,
)
from slack_workflow_engine.home.filters import HomeFilters  # noqa: E402


def test_build_home_view_populates_sections() -> None:
    base = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    summaries = [
        RequestSummary(
            id=10,
            workflow_type="refund",
            status="PENDING",
            created_by="U123",
            created_at=base,
            payload_json="{}",
            decided_by=None,
            decided_at=None,
        ),
        RequestSummary(
            id=11,
            workflow_type="expense",
            status="APPROVED",
            created_by="U123",
            created_at=base.replace(hour=13),
            payload_json="{}",
            decided_by="U456",
            decided_at=base.replace(hour=14),
        ),
    ]

    pending = [
        RequestSummary(
            id=20,
            workflow_type="refund",
            status="PENDING",
            created_by="U789",
            created_at=base.replace(day=2),
            payload_json="{}",
            decided_by=None,
            decided_at=None,
        )
    ]

    my_filters = HomeFilters(["refund", "expense"], ["PENDING"], None, None, "created_at", "desc", 10, 0)
    pending_filters = HomeFilters(["refund"], ["PENDING"], None, None, "created_at", "asc", 10, 0)
    my_pag = PaginationState(offset=0, limit=10, has_previous=False, has_more=True)
    pending_pag = PaginationState(offset=0, limit=10, has_previous=False, has_more=False)

    view = build_home_view(
        my_requests=summaries,
        pending_approvals=pending,
        my_filters=my_filters,
        pending_filters=pending_filters,
        my_pagination=my_pag,
        pending_pagination=pending_pag,
    )

    assert view["type"] == "home"
    blocks = view["blocks"]
    assert blocks[0]["type"] == "header"
    assert "Track progress" in blocks[1]["text"]["text"]
    my_section = blocks[5]["text"]["text"]
    assert "*My Requests*" in my_section
    assert "• *Refund* · `#10` · Pending · 2024-01-01 12:00 UTC" in my_section
    assert "• *Expense*" in my_section

    pending_section = blocks[9]["text"]["text"]
    assert "*Pending Approvals*" in pending_section
    assert "• *Refund* · `#20` · Pending" in pending_section
    actions = blocks[10]["elements"]
    action_ids = {element["action_id"] for element in actions}
    assert HOME_APPROVE_ACTION_ID in action_ids
    assert HOME_REJECT_ACTION_ID in action_ids


def test_placeholder_view_matches_empty_state() -> None:
    view = build_home_placeholder_view()

    blocks = view["blocks"]
    assert blocks[0]["type"] == "header"
    assert blocks[3]["type"] == "section"  # filters summary
    assert "*Filters*" in blocks[3]["text"]["text"]
    assert blocks[5]["text"]["text"].startswith("*My Requests*")
    assert blocks[7]["type"] == "actions"
    assert blocks[9]["text"]["text"].startswith("*Pending Approvals*")
    assert blocks[10]["type"] != "actions" or len(blocks[10].get("elements", [])) == 0  # placeholder has no quick actions
    assert blocks[11]["type"] == "actions"
