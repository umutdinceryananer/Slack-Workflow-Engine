from slack_workflow_engine.home import build_home_placeholder_view


def test_build_home_placeholder_view_snapshot() -> None:
    view = build_home_placeholder_view()

    expected = {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Slack Workflow Engine",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Centralised request workflows in one place. This Home tab will soon "
                        "show your recent requests, pending approvals, and quick actions."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*My Requests*\n"
                        "We'll list your recent submissions here with quick links to each request."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Pending Approvals*\n"
                        "Requests waiting on you appear in this section so you can respond quickly."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Shortcuts & Insights*\n"
                        "Fast actions and analytics will be available here in later phases."
                    ),
                },
            },
        ],
    }

    assert view == expected
