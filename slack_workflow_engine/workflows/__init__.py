"""Workflow configuration models, loaders, and builders."""

from pathlib import Path

from .loader import load_workflow_definition, load_workflow_definitions
from .models import ApproverConfig, FieldDefinition, WorkflowDefinition
from .modal import build_modal_view

WORKFLOW_DEFINITION_DIR = Path.cwd() / "workflows"

__all__ = [
    "ApproverConfig",
    "FieldDefinition",
    "WorkflowDefinition",
    "load_workflow_definition",
    "load_workflow_definitions",
    "build_modal_view",
    "WORKFLOW_DEFINITION_DIR",
]
