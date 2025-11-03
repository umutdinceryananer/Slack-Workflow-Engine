"""Tests for background task utilities."""

from __future__ import annotations

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.testing import capture_logs

from slack_workflow_engine.background import run_async


def test_run_async_propagates_structlog_context():
    """Trace IDs bound in the caller should be visible within the worker thread."""

    clear_contextvars()
    bind_contextvars(trace_id="trace-123")
    captured: dict[str, str] = {}

    future = run_async(lambda: captured.update(get_contextvars()))
    future.result(timeout=1)

    assert captured.get("trace_id") == "trace-123"

    clear_contextvars()


def test_run_async_accepts_explicit_trace_id():
    """A trace_id parameter should seed context for workers even if not bound in caller."""

    clear_contextvars()
    captured: dict[str, str] = {}

    future = run_async(lambda: captured.update(get_contextvars()), trace_id="trace-456")
    future.result(timeout=1)

    assert captured.get("trace_id") == "trace-456"

    clear_contextvars()


def test_run_async_preserves_trace_id_in_background_logs():
    """Structured log events from workers should include the propagated trace identifier."""

    clear_contextvars()

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        future = run_async(lambda: structlog.get_logger().info("background_event"), trace_id="trace-789")
        future.result(timeout=1)

    assert logs, "expected background_event log to be captured"
    event = logs[0]
    assert event.get("event") == "background_event"
    assert event.get("trace_id") == "trace-789"

    clear_contextvars()
