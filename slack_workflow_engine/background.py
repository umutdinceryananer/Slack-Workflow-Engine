"""Utilities for running background tasks."""

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


_executor = ThreadPoolExecutor(max_workers=4)


def run_async(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future:
    """Submit *func* to the shared thread pool and return a Future."""

    return _executor.submit(func, *args, **kwargs)
