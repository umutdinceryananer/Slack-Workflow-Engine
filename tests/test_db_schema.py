"""Tests for database schema creation."""

from datetime import UTC, datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine import Base, config
from slack_workflow_engine.db import get_engine, get_session_factory
from slack_workflow_engine.models import ApprovalDecision, Message, Request, StatusHistory


@pytest.fixture(autouse=True)
def override_database(monkeypatch, tmp_path):
    test_db = tmp_path / "test.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    config.get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def test_create_all_creates_expected_tables():
    engine = get_engine()
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "requests" in tables
    assert "messages" in tables
    assert "approvals" in tables
    assert "status_history" in tables

    request_columns = {column["name"] for column in inspector.get_columns("requests")}
    assert request_columns.issuperset({"type", "payload_json", "request_key"})

    approvals_columns = {column["name"] for column in inspector.get_columns("approvals")}
    assert approvals_columns.issuperset({"request_id", "level", "decision", "decided_by"})

    history_columns = {column["name"] for column in inspector.get_columns("status_history")}
    assert history_columns.issuperset({"request_id", "from_status", "to_status", "changed_by"})

    with engine.begin() as connection:
        connection.execute(
            Request.__table__.insert(),
            {
                "type": "refund",
                "created_by": "U1",
                "payload_json": "{}",
                "status": "PENDING",
                "request_key": "unique-key",
            },
        )
        connection.execute(
            Message.__table__.insert(),
            {
                "request_id": 1,
                "channel_id": "C1",
                "ts": "123.456",
            },
        )
        connection.execute(
            ApprovalDecision.__table__.insert(),
            {
                "request_id": 1,
                "level": 1,
                "decision": "PENDING",
                "decided_by": "U1",
                "decided_at": datetime.now(UTC),
                "source": "seed",
            },
        )
        connection.execute(
            StatusHistory.__table__.insert(),
            {
                "request_id": 1,
                "from_status": "PENDING",
                "to_status": "PENDING",
                "changed_at": datetime.now(UTC),
                "changed_by": "system",
            },
        )
        rows = connection.execute(Request.__table__.select()).fetchall()
        assert len(rows) == 1

    Base.metadata.drop_all(engine)
