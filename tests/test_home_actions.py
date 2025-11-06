import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.home import HOME_ATTACHMENT_BLOCK_ID, HOME_REASON_BLOCK_ID  # noqa: E402
from slack_workflow_engine.db import Base, get_engine, get_session_factory, session_scope  # noqa: E402
from slack_workflow_engine.models import ApprovalDecision, Message, Request  # noqa: E402


class DummyClient:
    def __init__(self):
        self.open_calls: list[dict] = []
        self.update_calls: list[dict] = []

    def views_open(self, **kwargs):
        self.open_calls.append(kwargs)
        return {"ok": True}

    def chat_update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"ok": True}


class RecordingLogger:
    def __init__(self) -> None:
        self.infos: list[tuple] = []
        self.warnings: list[tuple] = []
        self.errors: list[tuple] = []

    def info(self, *args, **kwargs):  # pragma: no cover - logger passed by Slack
        self.infos.append((args, kwargs))

    def warning(self, *args, **kwargs):  # pragma: no cover
        self.warnings.append((args, kwargs))

    def error(self, *args, **kwargs):  # pragma: no cover
        self.errors.append((args, kwargs))


@pytest.fixture(autouse=True)
def home_actions_env(monkeypatch, tmp_path):
    db_path = tmp_path / "home-actions.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "UAPP")
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


def _create_request(session, *, created_by="UCREATOR", status="PENDING"):
    request = Request(
        type="refund",
        created_by=created_by,
        payload_json=json.dumps({"amount": 100}),
        status=status,
        request_key=f"key-{created_by}-{status}",
    )
    session.add(request)
    session.commit()
    request_id = request.id
    workflow_type = request.type
    return request_id, workflow_type


def _create_request_with_message(session, *, created_by="UCREATOR", status="PENDING"):
    request_id, workflow_type = _create_request(session, created_by=created_by, status=status)
    message = Message(request_id=request_id, channel_id="CHOME", ts="1700000000.100")
    session.add(message)
    session.commit()
    return request_id, workflow_type, message.channel_id, message.ts


def _build_body(request_id, workflow_type, *, user_id):
    return {
        "user": {"id": user_id},
        "trigger_id": "TRIGGER-123",
        "actions": [
            {
                "value": json.dumps({"request_id": request_id, "workflow_type": workflow_type}),
                "block_id": f"home_pending_actions_{request_id}",
            }
        ],
    }


def _build_submission_body(
    request_id,
    workflow_type,
    *,
    decision,
    user_id,
    reason=None,
    attachment_url=None,
):
    values: dict[str, dict] = {}
    if reason is not None:
        values.setdefault("reason_block", {})["reason"] = {"value": reason}
    if attachment_url is not None:
        values.setdefault("attachment_block", {})["attachment_url"] = {"value": attachment_url}
    return {
        "user": {"id": user_id},
        "view": {
            "private_metadata": json.dumps(
                {"request_id": request_id, "workflow_type": workflow_type, "decision": decision}
            ),
            "state": {"values": values},
        },
    }


def test_home_approve_allows_authorized_user(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    logger = RecordingLogger()
    client = DummyClient()

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=client,
        logger=logger,
    )

    assert ack_payloads == [None]
    assert len(client.open_calls) == 1
    metadata = client.open_calls[0]["view"]["private_metadata"]
    payload = json.loads(metadata)
    assert payload["request_id"] == request_id
    assert payload["decision"] == "APPROVED"


def test_home_approve_blocks_unauthorized_user(monkeypatch):
    monkeypatch.setenv("APPROVER_USER_IDS", "UX")
    config.get_settings.cache_clear()

    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads
    assert not client.open_calls
    errors = ack_payloads[0]["errors"]
    assert any("not authorized" in message.lower() for message in errors.values())


def test_home_approve_blocks_decided_request(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR", status="APPROVED")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads
    assert not client.open_calls
    errors = ack_payloads[0]["errors"]
    assert any("already been decided" in message.lower() for message in errors.values())


def _sync_run_async(func, /, *args, **kwargs):
    """Execute run_async workloads synchronously in tests."""

    kwargs.pop("trace_id", None)
    return func(*args, **kwargs)


def test_home_decision_submission_approves_request_and_records(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type, _, _ = _create_request_with_message(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()
    monkeypatch.setattr(app_module, "run_async", _sync_run_async)

    body = _build_submission_body(
        request_id,
        workflow_type,
        decision="APPROVED",
        user_id="UAPP",
        reason="Looks good",
        attachment_url="https://example.com/proof.pdf",
    )

    app_module._handle_home_decision_submission(
        ack=ack,
        body=body,
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads == [{"response_action": "clear"}]
    assert client.update_calls

    factory = get_session_factory()
    with factory() as session:
        request = session.get(Request, request_id)
        assert request.status == "APPROVED"
        assert request.decided_by == "UAPP"
        approval = session.query(ApprovalDecision).filter_by(request_id=request_id).one()
        assert approval.decision == "APPROVED"
        assert approval.reason == "Looks good"
        assert approval.attachment_url == "https://example.com/proof.pdf"
        assert approval.source == "home"


def test_home_decision_submission_requires_reason_for_reject(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type, _, _ = _create_request_with_message(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()
    monkeypatch.setattr(app_module, "run_async", _sync_run_async)

    body = _build_submission_body(
        request_id,
        workflow_type,
        decision="REJECTED",
        user_id="UAPP",
    )

    app_module._handle_home_decision_submission(
        ack=ack,
        body=body,
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert HOME_REASON_BLOCK_ID in errors

    factory = get_session_factory()
    with factory() as session:
        request = session.get(Request, request_id)
        assert request.status == "PENDING"
        assert session.query(ApprovalDecision).count() == 0


def test_home_decision_submission_validates_attachment_url(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type, _, _ = _create_request_with_message(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()
    monkeypatch.setattr(app_module, "run_async", _sync_run_async)

    body = _build_submission_body(
        request_id,
        workflow_type,
        decision="APPROVED",
        user_id="UAPP",
        attachment_url="ftp://invalid",
    )

    app_module._handle_home_decision_submission(
        ack=ack,
        body=body,
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert HOME_ATTACHMENT_BLOCK_ID in errors

    factory = get_session_factory()
    with factory() as session:
        request = session.get(Request, request_id)
        assert request.status == "PENDING"
        assert session.query(ApprovalDecision).count() == 0


def test_home_decision_submission_blocks_unauthorized_user(monkeypatch):
    monkeypatch.setenv("APPROVER_USER_IDS", "UX")
    config.get_settings.cache_clear()

    with session_scope() as session:
        request_id, workflow_type, _, _ = _create_request_with_message(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    client = DummyClient()
    monkeypatch.setattr(app_module, "run_async", _sync_run_async)

    body = _build_submission_body(
        request_id,
        workflow_type,
        decision="APPROVED",
        user_id="UAPP",
    )

    app_module._handle_home_decision_submission(
        ack=ack,
        body=body,
        client=client,
        logger=RecordingLogger(),
    )

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert "authorized" in " ".join(errors.values()).lower()

    factory = get_session_factory()
    with factory() as session:
        request = session.get(Request, request_id)
        assert request.status == "PENDING"
        assert session.query(ApprovalDecision).count() == 0
