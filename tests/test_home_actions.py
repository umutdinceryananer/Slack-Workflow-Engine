import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.db import Base, get_engine, get_session_factory, session_scope  # noqa: E402
from slack_workflow_engine.models import Request  # noqa: E402


class DummyClient:
    pass


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


def _build_body(request_id, workflow_type, *, user_id):
    return {
        "user": {"id": user_id},
        "actions": [
            {
                "value": json.dumps({"request_id": request_id, "workflow_type": workflow_type}),
                "block_id": f"home_pending_actions_{request_id}",
            }
        ],
    }


def test_home_approve_allows_authorized_user(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    logger = RecordingLogger()

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=DummyClient(),
        logger=logger,
    )

    assert ack_payloads == [None]


def test_home_approve_blocks_unauthorized_user(monkeypatch):
    monkeypatch.setenv("APPROVER_USER_IDS", "UX")
    config.get_settings.cache_clear()

    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=DummyClient(),
        logger=RecordingLogger(),
    )

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert any("not authorized" in message.lower() for message in errors.values())


def test_home_approve_blocks_decided_request(monkeypatch):
    with session_scope() as session:
        request_id, workflow_type = _create_request(session, created_by="UCREATOR", status="APPROVED")

    ack_payloads = []

    def ack(payload=None):
        ack_payloads.append(payload)

    app_module._handle_home_approve_action(
        ack=ack,
        body=_build_body(request_id, workflow_type, user_id="UAPP"),
        client=DummyClient(),
        logger=RecordingLogger(),
    )

    assert ack_payloads
    errors = ack_payloads[0]["errors"]
    assert any("already been decided" in message.lower() for message in errors.values())
