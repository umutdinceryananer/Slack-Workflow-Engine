"""Services for storing workflow requests."""

from __future__ import annotations

from datetime import UTC, datetime

from slack_workflow_engine.db import session_scope
from slack_workflow_engine.models import Request


def save_request(*, workflow_type: str, created_by: str, payload_json: str, request_key: str) -> Request:
    """Persist a new workflow request and return the saved entity."""

    with session_scope() as session:
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
        return request
