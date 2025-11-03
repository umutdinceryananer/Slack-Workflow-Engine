"""Utilities for running background tasks."""

from contextvars import copy_context
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from structlog.contextvars import bind_contextvars, get_contextvars


_executor = ThreadPoolExecutor(max_workers=4)


def run_async(
    func: Callable[..., Any],
    /,
    *args: Any,
    trace_id: str | None = None,
    **kwargs: Any,
) -> Future:
    """Submit *func* to the shared thread pool and return a Future."""

    context = copy_context()

    if trace_id is not None:
        existing_trace = context.run(lambda: get_contextvars().get("trace_id"))

        if existing_trace != trace_id:

            context.run(lambda: bind_contextvars(trace_id=trace_id))

    def runner() -> Any:
        return context.run(func, *args, **kwargs)

    return _executor.submit(runner)
