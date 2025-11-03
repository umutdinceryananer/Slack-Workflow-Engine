"""Workflow configuration models, loaders, and builders."""

from pathlib import Path

from .loader import load_workflow_definition, load_workflow_definitions
from .models import ApproverConfig, FieldDefinition, WorkflowDefinition
from .modal import build_modal_view
from .messages import (
    build_request_message,
    build_request_decision_update,
    APPROVE_ACTION_ID,
    REJECT_ACTION_ID,
)

WORKFLOW_DEFINITION_DIR = Path.cwd() / "workflows"

__all__ = [
    "ApproverConfig",
    "FieldDefinition",
    "WorkflowDefinition",
    "load_workflow_definition",
    "load_workflow_definitions",
    "build_modal_view",
    "build_request_message",
    "build_request_decision_update",
    "APPROVE_ACTION_ID",
    "REJECT_ACTION_ID",
    "WORKFLOW_DEFINITION_DIR",
]
