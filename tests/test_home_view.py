from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.home import (  # noqa: E402
    RequestSummary,
    build_home_placeholder_view,
    build_home_view,
)


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

    view = build_home_view(my_requests=summaries, pending_approvals=pending)

    assert view["type"] == "home"
    blocks = view["blocks"]
    assert blocks[0]["type"] == "header"
    assert "Track progress" in blocks[1]["text"]["text"]
    my_section = blocks[3]["text"]["text"]
    assert "*My Requests*" in my_section
    assert "• *Refund* · `#10` · Pending · 2024-01-01 12:00 UTC" in my_section
    assert "• *Expense*" in my_section

    pending_section = blocks[5]["text"]["text"]
    assert "*Pending Approvals*" in pending_section
    assert "• *Refund* · `#20` · Pending" in pending_section


def test_placeholder_view_matches_empty_state() -> None:
    view = build_home_placeholder_view()

    expected = {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Slack Workflow Engine",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Centralised request workflows in one place. Track progress, respond to approvals, "
                        "and access quick actions from this Home tab."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*My Requests*\n_No recent requests yet._",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Pending Approvals*\n_Nothing waiting on you right now._",
                },
            },
        ],
    }

    assert view == expected
