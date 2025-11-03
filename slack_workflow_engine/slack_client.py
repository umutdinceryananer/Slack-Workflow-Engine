"""Thin wrapper utilities around the Slack WebClient."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from slack_sdk import WebClient


class SlackClient:
    """Encapsulate Slack WebClient interactions for easier testing."""

    def __init__(self, *, token: str | None = None, client: WebClient | None = None) -> None:
        if client is None and token is None:
            raise ValueError("Either an instantiated client or a bot token must be provided.")

        self._client = client or WebClient(token=token)

    @property
    def client(self) -> WebClient:
        """Expose the underlying WebClient for advanced use cases."""

        return self._client

    def post_message(
        self,
        *,
        channel: str,
        text: str,
        blocks: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Post a message with Block Kit content to a Slack channel."""

        return self._client.chat_postMessage(channel=channel, text=text, blocks=list(blocks))

    def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Update an existing Slack message."""

        return self._client.chat_update(channel=channel, ts=ts, text=text, blocks=list(blocks))
