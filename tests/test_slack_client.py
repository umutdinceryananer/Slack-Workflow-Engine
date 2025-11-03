"""Unit tests for the Slack WebClient wrapper."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.slack_client import SlackClient  # noqa: E402


class DummyWebClient:
    def __init__(self):
        self.calls = []

    def chat_postMessage(self, **kwargs):
        self.calls.append(("post", kwargs))
        return {"ok": True, "message": kwargs}

    def chat_update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {"ok": True, "message": kwargs}


def test_requires_token_or_client():
    with pytest.raises(ValueError):
        SlackClient()


def test_post_message_uses_underlying_client():
    dummy = DummyWebClient()
    client = SlackClient(client=dummy)

    response = client.post_message(channel="C123", text="hello", blocks=[{"type": "section"}])

    assert dummy.calls == [
        ("post", {"channel": "C123", "text": "hello", "blocks": [{"type": "section"}]}),
    ]
    assert response["ok"] is True
    assert client.client is dummy


def test_update_message_uses_underlying_client():
    dummy = DummyWebClient()
    client = SlackClient(client=dummy)

    response = client.update_message(
        channel="C123",
        ts="123.456",
        text="updated",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "Hi"}}],
    )

    assert dummy.calls[-1] == (
        "update",
        {
            "channel": "C123",
            "ts": "123.456",
            "text": "updated",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Hi"}}],
        },
    )
    assert response["ok"] is True
