"""Validators and helpers for Slack slash commands and submissions."""

from __future__ import annotations

from dataclasses import dataclass

from slack_workflow_engine.workflows import WORKFLOW_DEFINITION_DIR, load_workflow_definition


@dataclass
class WorkflowContext:
    workflow_type: str


def parse_slash_command(text: str) -> WorkflowContext:
    workflow_type = (text or "").strip().lower()
    if not workflow_type:
        raise ValueError("Workflow type is required.")
    return WorkflowContext(workflow_type=workflow_type)


def load_workflow_or_raise(workflow_type: str):
    file_path = WORKFLOW_DEFINITION_DIR / f"{workflow_type}.json"
    return load_workflow_definition(file_path)
