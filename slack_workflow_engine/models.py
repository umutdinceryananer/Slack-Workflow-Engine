"""SQLAlchemy models for workflow requests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from slack_workflow_engine.db import Base


class Request(Base):
    """Represents a workflow request instance."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
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
