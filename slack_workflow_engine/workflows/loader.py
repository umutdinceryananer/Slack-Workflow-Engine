"""Loaders for workflow definitions."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from .models import WorkflowDefinition


@lru_cache()
def load_workflow_definition(file_path: Path) -> WorkflowDefinition:
    """Load a workflow definition from a JSON file."""

    with file_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    return WorkflowDefinition.model_validate(data)


def load_workflow_definitions(directory: Path) -> Dict[str, WorkflowDefinition]:
    """Load every JSON workflow definition inside *directory* keyed by type."""

    definitions: Dict[str, WorkflowDefinition] = {}
    for file_path in directory.glob("*.json"):
        definition = load_workflow_definition(file_path)
        definitions[definition.type] = definition
    return definitions
