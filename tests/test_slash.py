"""Tests for workflow modal builder and slash command."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine import config  # noqa: E402
from slack_workflow_engine.workflows import build_modal_view, load_workflow_definition  # noqa: E402


@pytest.fixture
def settings_env(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SLACK_BOT_TOKEN", "token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("APPROVER_USER_IDS", "U1,U2")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config.get_settings.cache_clear()
    yield tmp_path
    config.get_settings.cache_clear()


@pytest.fixture
def workflow_definition(tmp_path):
    data = {
        "type": "demo",
        "title": "Demo Workflow",
        "fields": [
            {"name": "foo", "label": "Foo", "type": "text", "required": True},
            {"name": "bar", "label": "Bar", "type": "textarea"},
        ],
        "approvers": {"strategy": "sequential", "levels": [["U1"], ["U2"]]},
        "notify_channel": "C123",
    }
    file_path = tmp_path / "demo.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return load_workflow_definition(file_path)


def test_build_modal_view_constructs_all_fields(workflow_definition):
    view = build_modal_view(workflow_definition)

    assert view["callback_id"] == "workflow_submit:demo"
    assert len(view["blocks"]) == 2
    first_block = view["blocks"][0]
    assert first_block["block_id"] == "foo"
    assert first_block.get("optional") is False
    assert first_block["element"]["type"] == "plain_text_input"


def test_slash_command_opens_modal(monkeypatch, settings_env):
    workflows_dir = settings_env / "workflows"
    workflows_dir.mkdir()
    data = {
        "type": "refund",
        "title": "Refund",
        "fields": [{"name": "amount", "label": "Amount", "type": "number"}],
        "approvers": {"strategy": "sequential", "levels": [["U1"]]},
        "notify_channel": "CREFUND",
    }
    (workflows_dir / "refund.json").write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(app_module, "WORKFLOW_DEFINITION_DIR", workflows_dir)

    client_calls = []

    class DummyClient:
        def views_open(self, trigger_id, view):  # pragma: no cover - trivial
            client_calls.append((trigger_id, view))

    ack_calls = []

    def ack(payload=None):
        ack_calls.append(payload)

    command = {"text": "refund", "trigger_id": "123.456"}
    logger = app_module._create_bolt_app(config.get_settings()).logger

    def immediate_run(func, *args, **kwargs):
        func(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_async", immediate_run)

    app_module._handle_request_command(ack=ack, command=command, client=DummyClient(), logger=logger)

    assert ack_calls == [None]
    assert client_calls  # ensure modal scheduling occurred


def test_slash_command_unknown_workflow(monkeypatch, settings_env):
    workflows_dir = settings_env / "workflows"
    workflows_dir.mkdir()
    monkeypatch.setattr(app_module, "WORKFLOW_DEFINITION_DIR", workflows_dir)

    ack_payload = {}

    def ack(payload=None):
        ack_payload.update(payload or {})

    command = {"text": "missing", "trigger_id": "123"}
    logger = app_module._create_bolt_app(config.get_settings()).logger

    app_module._handle_request_command(ack=ack, command=command, client=None, logger=logger)

    assert "Workflow `missing` is not configured." in ack_payload["text"]
