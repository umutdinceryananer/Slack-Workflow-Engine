"""Services for storing workflow requests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from slack_workflow_engine.db import session_scope
from slack_workflow_engine.models import Message, Request, DuplicateRequestError


def save_request(*, workflow_type: str, created_by: str, payload_json: str, request_key: str) -> Request:
    """Persist a new workflow request and return the saved entity."""

    with session_scope() as session:
        existing = session.execute(
            select(Request.id).where(Request.request_key == request_key)
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateRequestError("Duplicate request submission.")

        request = Request(
            type=workflow_type,
            created_by=created_by,
            payload_json=payload_json,
            status="PENDING",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            request_key=request_key,
        )
        session.add(request)
        session.flush()
        session.refresh(request)
        session.expunge(request)
        return request


def save_message_reference(
    *,
    request_id: int,
    channel_id: str,
    ts: str,
    thread_ts: str | None = None,
) -> Message:
    """Persist the Slack message reference for a workflow request."""

    with session_scope() as session:
        message = Message(
            request_id=request_id,
            channel_id=channel_id,
            ts=ts,
            thread_ts=thread_ts,
        )
        session.add(message)
        session.flush()
        session.refresh(message)
        session.expunge(message)
        return message
