from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

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


def test_home_handler_publishes_when_not_debounced(monkeypatch):
    debouncer = SpyDebouncer(should_publish=True)
    monkeypatch.setattr(app_module, "HOME_DEBOUNCER", debouncer)

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

    monkeypatch.setattr(app_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(app_module, "list_recent_requests", fake_recent)
    monkeypatch.setattr(app_module, "list_pending_approvals", fake_pending)
    monkeypatch.setattr(app_module, "build_home_view", fake_build_view)
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: SimpleNamespace(home_recent_limit=5, home_pending_limit=7, approver_user_ids=["U1"]),
    )

    bolt_app = DummyBoltApp()
    app_module._register_home_handlers(bolt_app)
    handler = bolt_app.events["app_home_opened"]

    client = DummyClient()
    logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert recent_calls == [(dummy_session, "U123", 5)]
    assert pending_calls == [(dummy_session, "U123", 7)]
    assert view_calls == [([SimpleNamespace(id=1)], [SimpleNamespace(id=2)])]
    assert client.calls == [{"user_id": "U123", "view": {"type": "home", "blocks": []}}]


def test_home_handler_skips_publish_when_debounced(monkeypatch):
    debouncer = SpyDebouncer(should_publish=False)
    monkeypatch.setattr(app_module, "HOME_DEBOUNCER", debouncer)

    def fail(*args, **kwargs):  # pragma: no cover - sanity check
        raise AssertionError("Should not be called when debounced")

    @contextmanager
    def fake_scope():
        yield None

    monkeypatch.setattr(app_module, "session_scope", fake_scope)
    monkeypatch.setattr(app_module, "list_recent_requests", fail)
    monkeypatch.setattr(app_module, "list_pending_approvals", fail)
    monkeypatch.setattr(app_module, "build_home_view", fail)
    monkeypatch.setattr(app_module, "get_settings", lambda: None)

    bolt_app = DummyBoltApp()
    app_module._register_home_handlers(bolt_app)
    handler = bolt_app.events["app_home_opened"]

    client = DummyClient()
    logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert client.calls == []
