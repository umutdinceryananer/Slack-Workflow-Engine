"""Tests for request status transitions."""

from pathlib import Path
import sys
from datetime import UTC, datetime

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine import config
from slack_workflow_engine.db import Base, get_engine, get_session_factory
from slack_workflow_engine.models import (
    OptimisticLockError,
    Request,
    StatusHistory,
    StatusTransitionError,
    advance_request_status,
)


@pytest.fixture(autouse=True)
def setup_database(monkeypatch, tmp_path):
    db_path = tmp_path / "transitions.db"
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
    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def session(setup_database):
    factory = get_session_factory()
    with factory() as session:
        yield session


@pytest.fixture
def persisted_request(session):
    request = Request(
        type="refund",
        created_by="U1",
        payload_json="{}",
        status="PENDING",
        request_key="key-1",
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def test_valid_transition_advances_status(session, persisted_request):
    updated = advance_request_status(
        session,
        persisted_request,
        new_status="APPROVED",
        decided_by="U2",
        decided_at=datetime.now(UTC),
    )

    assert updated.status == "APPROVED"
    assert updated.version == 2
    assert updated.decided_by == "U2"

    history_entries = session.query(StatusHistory).filter_by(request_id=persisted_request.id).all()
    assert len(history_entries) == 1
    assert history_entries[0].from_status == "PENDING"
    assert history_entries[0].to_status == "APPROVED"
    assert history_entries[0].changed_by == "U2"


def test_invalid_transition_raises_error(session, persisted_request):
    with pytest.raises(StatusTransitionError):
        advance_request_status(
            session,
            persisted_request,
            new_status="PENDING",
            decided_by="U2",
        )


def test_optimistic_lock_detects_concurrent_update(setup_database):
    factory = get_session_factory()
    with factory() as session1:
        req = Request(
            type="refund",
            created_by="U1",
            payload_json="{}",
            status="PENDING",
            request_key="key-2",
        )
        session1.add(req)
        session1.commit()
        session1.refresh(req)
        request_id = req.id

        with factory() as session2:
            same_req_session2 = session2.get(Request, req.id)

            advance_request_status(session1, req, new_status="APPROVED", decided_by="U3")
            session1.commit()

            with pytest.raises(OptimisticLockError):
                advance_request_status(session2, same_req_session2, new_status="REJECTED", decided_by="U4")
