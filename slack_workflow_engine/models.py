"""SQLAlchemy models for workflow requests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, update
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session

from slack_workflow_engine.db import Base


class Request(Base):
    """Represents a workflow request instance."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    message: Mapped["Message"] = relationship("Message", back_populates="request", uselist=False, cascade="all, delete")


class Message(Base):
    """Stores the Slack message reference for a request."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_messages_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)

    request: Mapped[Request] = relationship("Request", back_populates="message")


class StatusTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""


class OptimisticLockError(Exception):
    """Raised when a concurrent update is detected."""


class DuplicateRequestError(Exception):
    """Raised when a duplicate request submission is detected."""


_ALLOWED_TRANSITIONS = {
    "PENDING": {"APPROVED", "REJECTED"},
    "APPROVED": set(),
    "REJECTED": set(),
}


def advance_request_status(
    session: Session,
    request: Request,
    *,
    new_status: str,
    decided_by: str,
    decided_at: datetime | None = None,
) -> Request:
    """Attempt to update request status with optimistic locking."""

    decided_time = decided_at or datetime.now(UTC)
    allowed = _ALLOWED_TRANSITIONS.get(request.status, set())
    if new_status not in allowed:
        raise StatusTransitionError(f"Cannot transition from {request.status} to {new_status}")

    stmt = (
        update(Request)
        .where(Request.id == request.id, Request.version == request.version)
        .values(
            status=new_status,
            decided_by=decided_by,
            decided_at=decided_time,
            updated_at=datetime.now(UTC),
            version=request.version + 1,
        )
    )
    result = session.execute(stmt)
    if result.rowcount != 1:
        session.rollback()
        raise OptimisticLockError(f"Request {request.id} was updated concurrently")

    session.refresh(request)
    return request
