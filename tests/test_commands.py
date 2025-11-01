"""Tests for slash command parsing and workflow loading."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.workflows.commands import (  # noqa: E402
    load_workflow_or_raise,
    parse_slash_command,
)


def test_parse_slash_command_normalises():
    context = parse_slash_command("  Refund  ")
    assert context.workflow_type == "refund"


@pytest.mark.parametrize("text", ["", "   "])
def test_parse_slash_command_requires_type(text):
    with pytest.raises(ValueError):
        parse_slash_command(text)


def test_load_workflow_or_raise(tmp_path, monkeypatch):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    definition_payload = {
        "type": "demo",
        "title": "Demo",
        "fields": [],
        "approvers": {"strategy": "sequential", "levels": [["U1"]]},
        "notify_channel": "C1",
    }
    (workflows_dir / "demo.json").write_text(
        json.dumps(definition_payload), encoding="utf-8"
    )
    monkeypatch.setattr(
        "slack_workflow_engine.workflows.commands.WORKFLOW_DEFINITION_DIR", workflows_dir
    )

    definition = load_workflow_or_raise("demo")
    assert definition.type == "demo"


def test_load_workflow_or_raise_missing(tmp_path, monkeypatch):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    monkeypatch.setattr(
        "slack_workflow_engine.workflows.commands.WORKFLOW_DEFINITION_DIR", workflows_dir
    )

    with pytest.raises(FileNotFoundError):
        load_workflow_or_raise("missing")
