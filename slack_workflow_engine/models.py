"""SQLAlchemy models for workflow requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, update
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

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
    approvals: Mapped[List["ApprovalDecision"]] = relationship(
        "ApprovalDecision",
        back_populates="request",
        cascade="all, delete-orphan",
    )
    status_history: Mapped[List["StatusHistory"]] = relationship(
        "StatusHistory",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="StatusHistory.changed_at",
    )


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


class ApprovalDecision(Base):
    """Stores a decision taken on a workflow request."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="channel")

    request: Mapped[Request] = relationship("Request", back_populates="approvals")


class StatusHistory(Base):
    """Audit log of request status transitions."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    changed_by: Mapped[str] = mapped_column(String(32), nullable=False)

    request: Mapped[Request] = relationship("Request", back_populates="status_history")


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
    previous_status = request.status
    allowed = _ALLOWED_TRANSITIONS.get(previous_status, set())
    if new_status not in allowed:
        raise StatusTransitionError(f"Cannot transition from {previous_status} to {new_status}")

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

    session.add(
        StatusHistory(
            request_id=request.id,
            from_status=previous_status,
            to_status=new_status,
            changed_at=decided_time,
            changed_by=decided_by,
        )
    )

    return request
