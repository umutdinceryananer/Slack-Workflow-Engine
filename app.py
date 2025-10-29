"""Application entry point for the Slack Workflow Engine MVP."""

from __future__ import annotations

from flask import Flask, jsonify, request
from slack_bolt import App as SlackApp
from slack_bolt.adapter.flask import SlackRequestHandler

from slack_workflow_engine.config import AppSettings, get_settings


def _create_bolt_app(settings: AppSettings) -> SlackApp:
    """Initialise the Slack Bolt application using validated settings."""

    return SlackApp(
        token=settings.bot_token,
        signing_secret=settings.signing_secret,
        token_verification_enabled=False,
    )


def create_app() -> Flask:
    """Create and configure the Flask application."""

    settings = get_settings()
    bolt_app = _create_bolt_app(settings)
    handler = SlackRequestHandler(bolt_app)
    flask_app = Flask(__name__)

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        return handler.handle(request)

    @flask_app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"ok": True})

    return flask_app


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    application = create_app()
    application.run(host="0.0.0.0", port=3000, debug=True)
