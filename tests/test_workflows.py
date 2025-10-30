"""Tests for workflow definition loading."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.workflows import (
    load_workflow_definition,
    load_workflow_definitions,
)


def test_load_workflow_definition_parses_valid_json(tmp_path):
    content = {
        "type": "refund",
        "title": "Refund Request",
        "fields": [
            {"name": "order_id", "label": "Order ID", "type": "text", "required": True},
            {"name": "amount", "label": "Amount", "type": "number"},
        ],
        "approvers": {
            "strategy": "sequential",
            "levels": [["U1"], ["U2", "U3"]],
        },
        "notify_channel": "C12345678",
    }
    file_path = tmp_path / "refund.json"
    file_path.write_text(json.dumps(content), encoding="utf-8")

    definition = load_workflow_definition(file_path)

    assert definition.type == "refund"
    assert definition.fields[0].required is True
    assert definition.approvers.strategy == "sequential"
    assert definition.notify_channel == "C12345678"


def test_invalid_field_type_raises_error(tmp_path):
    content = {
        "type": "invalid",
        "title": "Invalid Workflow",
        "fields": [
            {"name": "foo", "label": "Foo", "type": "unsupported"},
        ],
        "approvers": {
            "strategy": "sequential",
            "levels": [["U1"]],
        },
        "notify_channel": "C123",
    }
    file_path = tmp_path / "invalid.json"
    file_path.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ValueError):
        load_workflow_definition(file_path)


def test_directory_loader_returns_dictionary(tmp_path):
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()

    content = {
        "type": "expense",
        "title": "Expense Request",
        "fields": [
            {"name": "desc", "label": "Description", "type": "textarea"},
        ],
        "approvers": {
            "strategy": "parallel",
            "levels": [["U10", "U11"]],
        },
        "notify_channel": "CEXPENSE",
    }
    file_path = workflows_dir / "expense.json"
    file_path.write_text(json.dumps(content), encoding="utf-8")

    definitions = load_workflow_definitions(workflows_dir)

    assert "expense" in definitions
    assert definitions["expense"].approvers.strategy == "parallel"
