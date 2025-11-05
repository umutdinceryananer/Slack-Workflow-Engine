from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from slack_workflow_engine.home.views import build_home_placeholder_view  # noqa: E402


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

    bolt_app = DummyBoltApp()
    app_module._register_home_handlers(bolt_app)
    handler = bolt_app.events["app_home_opened"]

    client = DummyClient()
    logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert client.calls == [{"user_id": "U123", "view": build_home_placeholder_view()}]


def test_home_handler_skips_publish_when_debounced(monkeypatch):
    debouncer = SpyDebouncer(should_publish=False)
    monkeypatch.setattr(app_module, "HOME_DEBOUNCER", debouncer)

    bolt_app = DummyBoltApp()
    app_module._register_home_handlers(bolt_app)
    handler = bolt_app.events["app_home_opened"]

    client = DummyClient()
    logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    handler(event={"user": "U123"}, client=client, logger=logger)

    assert debouncer.calls == ["U123"]
    assert client.calls == []
