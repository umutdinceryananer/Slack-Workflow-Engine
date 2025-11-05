from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine import Base, config  # noqa: E402
from slack_workflow_engine.db import get_engine, get_session_factory  # noqa: E402
from slack_workflow_engine.home.data import (  # noqa: E402
    list_pending_approvals,
    list_recent_requests,
)
from slack_workflow_engine.models import Request  # noqa: E402


@pytest.fixture(autouse=True)
def database(monkeypatch, tmp_path):
    db_path = tmp_path / "home.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(engine)

    yield

    Base.metadata.drop_all(engine)
    engine.dispose()

    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _add_request(
    session,
    *,
    seq: int,
    workflow_type: str,
    created_by: str,
    created_at: datetime,
    status: str = "PENDING",
) -> None:
    session.add(
        Request(
            type=workflow_type,
            created_by=created_by,
            payload_json=json.dumps({"seq": seq}),
            status=status,
            created_at=created_at,
            updated_at=created_at,
            request_key=f"req-{seq}",
        )
    )


def test_list_recent_requests_returns_newest_first():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    factory = get_session_factory()

    with factory() as session:
        _add_request(session, seq=1, workflow_type="refund", created_by="U123", created_at=base - timedelta(minutes=2))
        _add_request(session, seq=2, workflow_type="refund", created_by="U999", created_at=base - timedelta(minutes=1))
        _add_request(session, seq=3, workflow_type="expense", created_by="U123", created_at=base)
        _add_request(session, seq=4, workflow_type="pto", created_by="U123", created_at=base + timedelta(minutes=1))
        session.commit()

    with factory() as session:
        results = list_recent_requests(session, user_id="U123", limit=2)

    assert [summary.workflow_type for summary in results] == ["pto", "expense"]
    assert all(summary.created_by == "U123" for summary in results)
    assert results[0].created_at > results[1].created_at


def test_list_recent_requests_empty_when_user_missing():
    factory = get_session_factory()
    with factory() as session:
        result = list_recent_requests(session, user_id="", limit=5)
    assert result == []


def test_list_pending_approvals_filters_by_status_and_type():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    factory = get_session_factory()

    with factory() as session:
        _add_request(session, seq=1, workflow_type="refund", created_by="U123", created_at=base)
        _add_request(session, seq=2, workflow_type="refund", created_by="U456", created_at=base + timedelta(minutes=1))
        _add_request(
            session,
            seq=3,
            workflow_type="expense",
            created_by="U789",
            created_at=base + timedelta(minutes=2),
        )
        _add_request(
            session,
            seq=4,
            workflow_type="refund",
            created_by="U789",
            created_at=base + timedelta(minutes=3),
            status="APPROVED",
        )
        _add_request(
            session,
            seq=5,
            workflow_type="refund",
            created_by="U1",
            created_at=base + timedelta(minutes=4),
        )
        session.commit()

    with factory() as session:
        results = list_pending_approvals(
            session,
            approver_id="U1",
            workflow_types=("refund",),
            limit=2,
        )

    assert len(results) == 2
    assert [summary.workflow_type for summary in results] == ["refund", "refund"]
    assert [summary.status for summary in results] == ["PENDING", "PENDING"]
    assert results[0].created_at < results[1].created_at
    assert all(summary.created_by != "U1" for summary in results)


def test_list_pending_approvals_empty_for_unknown_user():
    factory = get_session_factory()
    with factory() as session:
        result = list_pending_approvals(session, approver_id="", limit=5)
    assert result == []


def test_list_recent_requests_supports_filters_sort_and_offset():
    base = datetime(2024, 5, 1, tzinfo=UTC)
    factory = get_session_factory()

    with factory() as session:
        _add_request(session, seq=1, workflow_type="refund", created_by="U999", created_at=base - timedelta(days=2))
        _add_request(session, seq=2, workflow_type="refund", created_by="U123", created_at=base - timedelta(days=2), status="APPROVED")
        _add_request(session, seq=3, workflow_type="expense", created_by="U123", created_at=base - timedelta(days=1))
        _add_request(session, seq=4, workflow_type="expense", created_by="U123", created_at=base)
        _add_request(session, seq=5, workflow_type="expense", created_by="U123", created_at=base + timedelta(days=1))
        session.commit()

    with factory() as session:
        results = list_recent_requests(
            session,
            user_id="U123",
            workflow_types=["expense"],
            statuses=["PENDING"],
            start_at=base - timedelta(days=2),
            end_at=base,
            sort_by="created_at",
            sort_order="asc",
            offset=1,
            limit=1,
        )

    assert len(results) == 1
    assert results[0].id == 4
    assert results[0].workflow_type == "expense"
    assert results[0].status == "PENDING"


def test_list_pending_approvals_supports_sort_and_offset():
    base = datetime(2024, 6, 1, tzinfo=UTC)
    factory = get_session_factory()

    with factory() as session:
        _add_request(session, seq=1, workflow_type="refund", created_by="U100", created_at=base, status="PENDING")
        _add_request(session, seq=2, workflow_type="expense", created_by="U101", created_at=base + timedelta(hours=1), status="PENDING")
        _add_request(session, seq=3, workflow_type="refund", created_by="U102", created_at=base + timedelta(hours=2), status="APPROVED")
        _add_request(session, seq=4, workflow_type="pto", created_by="U103", created_at=base + timedelta(hours=3), status="PENDING")
        session.commit()

    with factory() as session:
        results = list_pending_approvals(
            session,
            approver_id="U200",
            statuses=["PENDING"],
            sort_by="type",
            sort_order="desc",
            offset=1,
            limit=2,
        )

    assert len(results) == 2
    assert [summary.workflow_type for summary in results] == ["pto", "expense"]
