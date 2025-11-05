from datetime import timedelta

import pytest

from slack_workflow_engine.home.debounce import HomeDebouncer


class FakeTimer:
    def __init__(self, start: float = 0.0) -> None:
        self._current = start

    def advance(self, seconds: float) -> None:
        self._current += seconds

    def __call__(self) -> float:
        return self._current


def test_home_debouncer_allows_single_publish_within_window() -> None:
    timer = FakeTimer()
    debouncer = HomeDebouncer(window=timedelta(seconds=5), timer=timer)

    assert debouncer.should_publish("U123") is True
    assert debouncer.should_publish("U123") is False

    timer.advance(4)
    assert debouncer.should_publish("U123") is False

    timer.advance(1)
    assert debouncer.should_publish("U123") is True


def test_debouncer_isolated_by_user() -> None:
    timer = FakeTimer()
    debouncer = HomeDebouncer(window=timedelta(seconds=5), timer=timer)

    assert debouncer.should_publish("U123") is True
    assert debouncer.should_publish("U456") is True
    assert debouncer.should_publish("U123") is False


def test_clear_removes_single_user_timestamp() -> None:
    timer = FakeTimer()
    debouncer = HomeDebouncer(window=timedelta(seconds=5), timer=timer)

    debouncer.should_publish("U123")
    assert debouncer.should_publish("U123") is False

    debouncer.clear("U123")
    assert debouncer.should_publish("U123") is True


def test_clear_allows_reset_of_all_users() -> None:
    timer = FakeTimer()
    debouncer = HomeDebouncer(window=timedelta(seconds=5), timer=timer)

    debouncer.should_publish("U123")
    debouncer.should_publish("U456")

    debouncer.clear()

    assert debouncer.should_publish("U123") is True
    assert debouncer.should_publish("U456") is True


def test_invalid_window_raises_value_error() -> None:
    with pytest.raises(ValueError):
        HomeDebouncer(window=timedelta(seconds=0))
