from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402


class DummyBoltApp:
    def __init__(self) -> None:
        self.events = {}

    def event(self, name):
        def decorator(func):
            self.events[name] = func
            return func

        return decorator


class SpyDebouncer:
    def __init__(self, should_publish: bool) -> None:
        self.should_publish_result = should_publish
        self.calls = []

    def should_publish(self, user_id: str):
        self.calls.append(user_id)
        return self.should_publish_result

    def clear(self, user_id=None) -> None:  # pragma: no cover - required for interface parity
        self.cleared = user_id


class DummyClient:
    def __init__(self) -> None:
        self.calls = []

    def views_publish(self, *, user_id, view):
        self.calls.append({"user_id": user_id, "view": view})


class RecordingLogger:
    def __init__(self) -> None:
        self.info_calls = []
        self.error_calls = []

    def info(self, message, **kwargs):
        self.info_calls.append((message, kwargs))

    def error(self, message, **kwargs):
        self.error_calls.append((message, kwargs))


class RecordingStructLogger(RecordingLogger):
    def __init__(self) -> None:
        super().__init__()
        self.bind_calls = []

    def bind(self, **kwargs):
        self.bind_calls.append(kwargs)
        return self


def _register_handler(monkeypatch, debouncer, *, session_scope, recent_fn, pending_fn, build_view, settings):
    monkeypatch.setattr(app_module, "HOME_DEBOUNCER", debouncer)
    monkeypatch.setattr(app_module, "session_scope", session_scope)
    monkeypatch.setattr(app_module, "list_recent_requests", recent_fn)
    monkeypatch.setattr(app_module, "list_pending_approvals", pending_fn)
    monkeypatch.setattr(app_module, "build_home_view", build_view)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)

    bolt_app = DummyBoltApp()
    app_module._register_home_handlers(bolt_app)
    return bolt_app.events["app_home_opened"]


def test_home_handler_publishes_when_not_debounced(monkeypatch):
    debouncer = SpyDebouncer(should_publish=True)

    dummy_session = object()

    @contextmanager
    def fake_session_scope():
        yield dummy_session

    recent_calls = []
    pending_calls = []

    def fake_recent(session, *, user_id, limit):
        recent_calls.append((session, user_id, limit))
        return [SimpleNamespace(id=1)]

    def fake_pending(session, *, approver_id, limit):
        pending_calls.append((session, approver_id, limit))
        return [SimpleNamespace(id=2)]

    view_calls = []

    def fake_build_view(*, my_requests, pending_approvals):
        view_calls.append((my_requests, pending_approvals))
        return {"type": "home", "blocks": []}

    struct_logger = RecordingStructLogger()
    monkeypatch.setattr(app_module.structlog, "get_logger", lambda: struct_logger)

    handler = _register_handler(
        monkeypatch,
        debouncer,
        session_scope=fake_session_scope,
        recent_fn=fake_recent,
        pending_fn=fake_pending,
        build_view=fake_build_view,
        settings=SimpleNamespace(home_recent_limit=5, home_pending_limit=7),
    )

    client = DummyClient()
    logger = RecordingLogger()

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert recent_calls == [(dummy_session, "U123", 5)]
    assert pending_calls == [(dummy_session, "U123", 7)]
    assert view_calls == [([SimpleNamespace(id=1)], [SimpleNamespace(id=2)])]
    assert client.calls == [{"user_id": "U123", "view": {"type": "home", "blocks": []}}]
    assert any(message == "app_home_data_prepared" and kwargs == {"recent_count": 1, "pending_count": 1} for message, kwargs in struct_logger.info_calls)


def test_home_handler_skips_publish_when_debounced(monkeypatch):
    debouncer = SpyDebouncer(should_publish=False)
    monkeypatch.setattr(app_module, "HOME_DEBOUNCER", debouncer)

    def fail(*args, **kwargs):  # pragma: no cover - sanity check
        raise AssertionError("Should not be called when debounced")

    @contextmanager
    def fake_scope():
        yield None

    handler = _register_handler(
        monkeypatch,
        debouncer,
        session_scope=fake_scope,
        recent_fn=fail,
        pending_fn=fail,
        build_view=fail,
        settings=None,
    )

    client = DummyClient()
    logger = RecordingLogger()

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert client.calls == []


def test_home_handler_handles_empty_data(monkeypatch):
    debouncer = SpyDebouncer(should_publish=True)

    @contextmanager
    def fake_scope():
        yield None

    struct_logger = RecordingStructLogger()
    monkeypatch.setattr(app_module.structlog, "get_logger", lambda: struct_logger)

    handler = _register_handler(
        monkeypatch,
        debouncer,
        session_scope=fake_scope,
        recent_fn=lambda *_, **__: [],
        pending_fn=lambda *_, **__: [],
        build_view=lambda *, my_requests, pending_approvals: {
            "type": "home",
            "blocks": [my_requests, pending_approvals],
        },
        settings=SimpleNamespace(home_recent_limit=3, home_pending_limit=3),
    )

    client = DummyClient()
    logger = RecordingLogger()

    handler(event={"user": "U456"}, client=client, logger=logger)

    assert client.calls == [{"user_id": "U456", "view": {"type": "home", "blocks": [[], []]}}]
    assert any(message == "app_home_data_prepared" and kwargs == {"recent_count": 0, "pending_count": 0} for message, kwargs in struct_logger.info_calls)


def test_home_handler_logs_on_slack_error(monkeypatch):
    debouncer = SpyDebouncer(should_publish=True)

    @contextmanager
    def fake_scope():
        yield None

    error_logger = RecordingLogger()
    struct_logger = RecordingStructLogger()
    monkeypatch.setattr(app_module.structlog, "get_logger", lambda: struct_logger)

    handler = _register_handler(
        monkeypatch,
        debouncer,
        session_scope=fake_scope,
        recent_fn=lambda *_, **__: [],
        pending_fn=lambda *_, **__: [],
        build_view=lambda **_: {"type": "home", "blocks": []},
        settings=SimpleNamespace(home_recent_limit=5, home_pending_limit=5),
    )

    class FailingClient(DummyClient):
        def views_publish(self, *, user_id, view):
            response = SlackResponse(
                client=None,
                http_verb="POST",
                api_url="https://slack",  # pragma: no cover
                req_args={},
                data={"error": "rate_limited"},
                headers={},
                status_code=429,
            )
            raise SlackApiError(message="Too many requests", response=response)

    client = FailingClient()

    handler(event={"user": "U789"}, client=client, logger=error_logger)

    assert any(message == "app_home_publish_failed" for message, _ in struct_logger.error_calls)
    assert any(message == "Failed to publish App Home view" for message, _ in error_logger.error_calls)
