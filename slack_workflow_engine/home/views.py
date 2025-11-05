"""Builders for Slack App Home views."""

from __future__ import annotations

from typing import Any, Dict, List


def _divider() -> Dict[str, Any]:
    """Return a reusable divider block."""
    return {"type": "divider"}


def _section(text: str) -> Dict[str, Any]:
    """Return a simple mrkdwn section block."""
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": text,
        },
    }


def _actionless_section(title: str, body: str) -> Dict[str, Any]:
    """Return a titled section with body text and no interactive elements."""
    return _section(f"*{title}*\n{body}")


def build_home_placeholder_view() -> Dict[str, Any]:
    """Build the initial placeholder Home tab structure.

    This view intentionally uses static placeholder content. Later commits will
    populate the sections with real data and interactive components.
    """

    header_block: Dict[str, Any] = {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Slack Workflow Engine",
            "emoji": True,
        },
    }

    intro_block = _section(
        "Centralised request workflows in one place. This Home tab will soon show "
        "your recent requests, pending approvals, and quick actions."
    )

    placeholders: List[Dict[str, Any]] = [
        _actionless_section(
            "My Requests",
            "We'll list your recent submissions here with quick links to each request.",
        ),
        _actionless_section(
            "Pending Approvals",
            "Requests waiting on you appear in this section so you can respond quickly.",
        ),
        _actionless_section(
            "Shortcuts & Insights",
            "Fast actions and analytics will be available here in later phases.",
        ),
    ]

    blocks: List[Dict[str, Any]] = [header_block, intro_block, _divider()]
    for placeholder in placeholders:
        blocks.extend([placeholder, _divider()])

    # Remove the trailing divider to avoid redundant separators at the end.
    blocks = blocks[:-1]

    return {
        "type": "home",
        "blocks": blocks,
    }
