"""Unit tests for workflow state helpers and decision application."""

from datetime import UTC, datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import Base, get_engine, get_session_factory, session_scope  # noqa: E402
from slack_workflow_engine.models import Request  # noqa: E402
from slack_workflow_engine.workflows import WorkflowDefinition  # noqa: E402
from slack_workflow_engine.workflows.models import ApproverConfig  # noqa: E402
from slack_workflow_engine.workflows.state import (  # noqa: E402
    compute_level_runtime,
    derive_initial_status,
    extract_level_from_status,
    format_status_text,
    pending_status,
)


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch, tmp_path):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2,UTIE")
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


def _definition(levels):
    return WorkflowDefinition(
        type="demo",
        title="Demo",
        fields=[],
        approvers=ApproverConfig.model_validate({"strategy": "sequential", "levels": levels}),
        notify_channel="C123",
    )


def _decision(level, decided_by, decision):
    return SimpleNamespace(
        level=level,
        decided_by=decided_by,
        decision=decision,
        decided_at=datetime.now(UTC),
    )


def test_pending_status_helpers():
    assert pending_status(2) == "PENDING_L2"
    assert extract_level_from_status("PENDING_L5") == 5
    assert derive_initial_status(_definition([{"members": ["U1"]}])) == "PENDING_L1"


def test_compute_level_runtime_with_quorum_tracking():
    definition = _definition(
        [
            {"members": ["U1", "U2", "U3"], "quorum": 2},
        ]
    )
    decisions = [
        _decision(1, "U1", "APPROVED"),
    ]
    runtime = compute_level_runtime(definition=definition, status="PENDING_L1", decisions=decisions)
    assert runtime.quorum == 2
    assert runtime.approvals == 1
    assert runtime.waiting_on == ["U2", "U3"]
    assert "Waiting on" in format_status_text(runtime)


def test_compute_level_runtime_tie_breaker_wait_list():
    definition = _definition(
        [
            {"members": ["U1", "U2"], "tie_breaker": "UTIE"},
        ]
    )
    decisions = [
        _decision(1, "U1", "APPROVED"),
        _decision(1, "U2", "REJECTED"),
    ]
    runtime = compute_level_runtime(definition=definition, status="PENDING_L1", decisions=decisions)
    assert runtime.awaiting_tie_breaker is True
    assert runtime.waiting_on == ["UTIE"]
    assert "Awaiting tie-breaker" in format_status_text(runtime)


def test_apply_level_decision_advances_levels():
    definition = _definition(
        [
            {"members": ["U1"], "quorum": 1},
            {"members": ["U2"], "quorum": 1},
        ]
    )
    with session_scope() as session:
        request = Request(
            type="demo",
            created_by="CREATOR",
            payload_json="{}",
            status="PENDING_L1",
            request_key="demo-advance",
        )
        session.add(request)
        session.commit()
        session.refresh(request)
        request_id = request.id

        result_l1 = app_module._apply_level_decision(
            session,
            request=request,
            definition=definition,
            user_id="U1",
            decision="APPROVED",
            source="channel",
            reason=None,
            attachment_url=None,
        )
        session.commit()
        session.refresh(request)

    assert result_l1.final_decision is None
    assert result_l1.approver_level == 2

    with session_scope() as session:
        refreshed = session.get(Request, request_id)
        assert refreshed.status == "PENDING_L2"


def test_apply_level_decision_tie_breaker_resolution():
    definition = _definition(
        [
            {"members": ["U1", "U2"], "tie_breaker": "UTIE"},
        ]
    )

    with session_scope() as session:
        request = Request(
            type="demo",
            created_by="CREATOR",
            payload_json="{}",
            status="PENDING_L1",
            request_key="demo-tie",
        )
        session.add(request)
        session.commit()
        session.refresh(request)
        request_id = request.id

        app_module._apply_level_decision(
            session,
            request=request,
            definition=definition,
            user_id="U1",
            decision="APPROVED",
            source="channel",
            reason=None,
            attachment_url=None,
        )
        app_module._apply_level_decision(
            session,
            request=request,
            definition=definition,
            user_id="U2",
            decision="REJECTED",
            source="channel",
            reason=None,
            attachment_url=None,
        )
        result_tie = app_module._apply_level_decision(
            session,
            request=request,
            definition=definition,
            user_id="UTIE",
            decision="APPROVED",
            source="channel",
            reason=None,
            attachment_url=None,
        )
        session.commit()
        session.refresh(request)

    assert result_tie.final_decision == "APPROVED"

    with session_scope() as session:
        refreshed = session.get(Request, request_id)
        assert refreshed.status == "APPROVED"
