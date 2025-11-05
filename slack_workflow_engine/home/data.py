"""Data access helpers for App Home content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from slack_workflow_engine.models import Request


@dataclass(frozen=True)
class RequestSummary:
    """Lightweight representation of a workflow request row."""

    id: int
    workflow_type: str
    status: str
    created_by: str
    created_at: datetime
    payload_json: str
    decided_by: str | None
    decided_at: datetime | None


def _to_summaries(session: Session, statement: Select) -> List[RequestSummary]:
    rows = session.scalars(statement).all()
    return [
        RequestSummary(
            id=row.id,
            workflow_type=row.type,
            status=row.status,
            created_by=row.created_by,
            created_at=row.created_at,
            payload_json=row.payload_json,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
        )
        for row in rows
    ]


def list_recent_requests(session: Session, *, user_id: str, limit: int = 10) -> List[RequestSummary]:
    """Return the latest requests created by *user_id*, newest first."""

    if not user_id:
        return []

    statement = (
        select(Request)
        .where(Request.created_by == user_id)
        .order_by(Request.created_at.desc())
        .limit(limit)
    )

    return _to_summaries(session, statement)


def list_pending_approvals(
    session: Session,
    *,
    approver_id: str,
    limit: int = 10,
    workflow_types: Sequence[str] | Iterable[str] | None = None,
) -> List[RequestSummary]:
    """Return pending requests that require attention from *approver_id*.

    The current implementation assumes that approver eligibility is managed
    at a higher layer. Optional *workflow_types* can be supplied to narrow
    results to specific workflows.
    """

    if not approver_id:
        return []

    statement = select(Request).where(Request.status == "PENDING")

    if workflow_types:
        filter_types = tuple(dict.fromkeys(workflow_types))
        statement = statement.where(Request.type.in_(filter_types))

    statement = statement.order_by(Request.created_at.asc()).limit(limit)

    return _to_summaries(session, statement)
