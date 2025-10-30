"""Tests for background task utilities."""

import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.background import run_async  # noqa: E402


def test_run_async_executes_function_in_background():
    result = []

    def task():
        time.sleep(0.05)
        result.append("done")

    future = run_async(task)
    # Execution should not block immediately
    assert result == []
    assert future.result(timeout=1) is None
    assert result == ["done"]

