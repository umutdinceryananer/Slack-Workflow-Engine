"""Data access helpers for App Home content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, List, Literal, Sequence

from sqlalchemy import Select, select, or_
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


def _normalise_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _apply_filters(
    statement: Select,
    *,
    workflow_types: Sequence[str] | Iterable[str] | None,
    statuses: Sequence[str] | Iterable[str] | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> Select:
    if workflow_types:
        statement = statement.where(Request.type.in_(tuple(dict.fromkeys(workflow_types))))

    if statuses:
        clauses = []
        for status in dict.fromkeys(statuses):
            if status.upper() == "PENDING":
                clauses.append(Request.status.like("PENDING%"))
            else:
                clauses.append(Request.status == status)
        if clauses:
            statement = statement.where(or_(*clauses))

    start_at = _normalise_dt(start_at)
    end_at = _normalise_dt(end_at)

    if start_at is not None:
        statement = statement.where(Request.created_at >= start_at)

    if end_at is not None:
        statement = statement.where(Request.created_at <= end_at)

    return statement


def _apply_sort(statement: Select, *, sort_by: str, sort_order: Literal["asc", "desc"] = "desc") -> Select:
    order = sort_order.lower()
    descending = order == "desc"

    if sort_by == "status":
        clause = Request.status.desc() if descending else Request.status.asc()
    elif sort_by == "type":
        clause = Request.type.desc() if descending else Request.type.asc()
    else:
        clause = Request.created_at.desc() if descending else Request.created_at.asc()

    return statement.order_by(clause)


def _apply_query(statement: Select, *, query: str | None) -> Select:
    if not query:
        return statement

    term = f"%{query}%"
    clauses = [
        Request.type.ilike(term),
        Request.created_by.ilike(term),
        Request.payload_json.ilike(term),
    ]

    if query.isdigit():
        clauses.append(Request.id == int(query))

    return statement.where(or_(*clauses))


def list_recent_requests(
    session: Session,
    *,
    user_id: str,
    limit: int = 10,
    offset: int = 0,
    workflow_types: Sequence[str] | Iterable[str] | None = None,
    statuses: Sequence[str] | Iterable[str] | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: Literal["created_at", "status", "type"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    query: str | None = None,
) -> List[RequestSummary]:
    """Return requests created by *user_id* applying optional filters."""

    if not user_id:
        return []

    statement = select(Request).where(Request.created_by == user_id)
    statement = _apply_filters(
        statement,
        workflow_types=workflow_types,
        statuses=statuses,
        start_at=start_at,
        end_at=end_at,
    )

    statement = _apply_sort(statement, sort_by=sort_by, sort_order=sort_order)
    statement = _apply_query(statement, query=query)
    statement = statement.offset(max(offset, 0)).limit(limit)

    return _to_summaries(session, statement)


def list_pending_approvals(
    session: Session,
    *,
    approver_id: str,
    limit: int = 10,
    offset: int = 0,
    workflow_types: Sequence[str] | Iterable[str] | None = None,
    statuses: Sequence[str] | Iterable[str] | None = ("PENDING",),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: Literal["created_at", "status", "type"] = "created_at",
    sort_order: Literal["asc", "desc"] = "asc",
    query: str | None = None,
) -> List[RequestSummary]:
    """Return requests awaiting the attention of *approver_id* with filters."""

    if not approver_id:
        return []

    statement = select(Request).where(Request.created_by != approver_id)

    statement = _apply_filters(
        statement,
        workflow_types=workflow_types,
        statuses=statuses,
        start_at=start_at,
        end_at=end_at,
    )

    statement = _apply_sort(statement, sort_by=sort_by, sort_order=sort_order)
    statement = _apply_query(statement, query=query)
    statement = statement.offset(max(offset, 0)).limit(limit)

    return _to_summaries(session, statement)
