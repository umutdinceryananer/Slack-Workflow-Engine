"""Debounce helpers for Slack App Home publications."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Callable, Dict


class HomeDebouncer:
    """Keep per-user timestamps to prevent redundant Home publishes."""

    def __init__(
        self,
        *,
        window: timedelta = timedelta(seconds=5),
        timer: Callable[[], float] | None = None,
    ) -> None:
        if window.total_seconds() <= 0:
            raise ValueError("Debounce window must be greater than zero seconds.")

        self._window = window
        self._timer = timer or time.monotonic
        self._lock = threading.Lock()
        self._last_published: Dict[str, float] = {}

    def should_publish(self, user_id: str) -> bool:
        """Return True when a publish should proceed for *user_id*.

        When True is returned, the internal timestamp is updated. Calls inside
        the debounce window return False, indicating the caller should skip the
        publish to respect rate limits.
        """

        if not user_id:
            # If we cannot identify the user, avoid blocking the publish.
            return True

        now = self._timer()
        threshold = self._window.total_seconds()

        with self._lock:
            last = self._last_published.get(user_id)

            if last is None or now - last >= threshold:
                self._last_published[user_id] = now
                return True

            return False

    def clear(self, user_id: str | None = None) -> None:
        """Clear stored timestamps.

        - When *user_id* is provided, only that user's timestamp is removed.
        - When *user_id* is None, all entries are cleared.
        """

        with self._lock:
            if user_id is None:
                self._last_published.clear()
            else:
                self._last_published.pop(user_id, None)
