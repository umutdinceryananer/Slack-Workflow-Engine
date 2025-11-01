"""Application entry point for the Slack Workflow Engine MVP."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, request
from pydantic import ValidationError
from slack_bolt import App as SlackApp
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.errors import SlackApiError

from slack_workflow_engine.background import run_async
from slack_workflow_engine.config import AppSettings, get_settings
from slack_workflow_engine.security import (
    SLACK_SIGNATURE_HEADER,
    SLACK_TIMESTAMP_HEADER,
    is_valid_slack_request,
)
from slack_workflow_engine.workflows import (
    WORKFLOW_DEFINITION_DIR,
    build_modal_view,
    load_workflow_definition,
)


def _create_bolt_app(settings: AppSettings) -> SlackApp:
    """Initialise the Slack Bolt application using validated settings."""

    return SlackApp(
        token=settings.bot_token,
        signing_secret=settings.signing_secret,
        token_verification_enabled=False,
    )


def _register_error_handlers(flask_app: Flask) -> None:
    """Register a JSON error handler that attaches a trace identifier."""

    @flask_app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):  # type: ignore[override]
        trace_id = str(uuid4())
        flask_app.logger.exception(
            "Unhandled application error", extra={"trace_id": trace_id}, exc_info=error
        )
        response = jsonify({"error": "internal_server_error", "trace_id": trace_id})
        response.status_code = 500
        return response


def _load_workflow_definition_by_type(workflow_type: str):
    file_path = WORKFLOW_DEFINITION_DIR / f"{workflow_type}.json"
    return load_workflow_definition(file_path)


def _register_slash_handlers(bolt_app: SlackApp) -> None:
    WORKFLOW_DEFINITION_DIR.mkdir(parents=True, exist_ok=True)

    @bolt_app.command("/request")
    def handle_request(ack, respond, command, client, logger):
        workflow_type = (command.get("text") or "").strip().lower()
        if not workflow_type:
            ack(
                {
                    "response_type": "ephemeral",
                    "text": "Please specify a workflow type, e.g. `/request refund`.",
                }
            )
            return

        try:
            definition = _load_workflow_definition_by_type(workflow_type)
        except FileNotFoundError:
            ack(
                {
                    "response_type": "ephemeral",
                    "text": f"Workflow `{workflow_type}` is not configured.",
                }
            )
            return
        except ValidationError:
            logger.exception("Invalid workflow definition", extra={"workflow_type": workflow_type})
            ack(
                {
                    "response_type": "ephemeral",
                    "text": "This workflow definition is invalid. Please contact an administrator.",
                }
            )
            return

        view = build_modal_view(definition)
        trigger_id = command.get("trigger_id")
        ack()

        def open_modal() -> None:
            try:
                client.views_open(trigger_id=trigger_id, view=view)
            except SlackApiError as exc:  # pragma: no cover - network dependent
                logger.error(
                    "Failed to open workflow modal",
                    extra={"workflow_type": workflow_type, "error": exc.response.get("error")},
                )

        run_async(open_modal)


def create_app() -> Flask:
    """Create and configure the Flask application."""

    settings = get_settings()
    bolt_app = _create_bolt_app(settings)
    handler = SlackRequestHandler(bolt_app)
    flask_app = Flask(__name__)

    _register_error_handlers(flask_app)
    _register_slash_handlers(bolt_app)

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        raw_body = request.get_data(as_text=True)
        timestamp = request.headers.get(SLACK_TIMESTAMP_HEADER, "")
        signature = request.headers.get(SLACK_SIGNATURE_HEADER, "")
        if not is_valid_slack_request(
            signing_secret=settings.signing_secret,
            timestamp=timestamp,
            body=raw_body,
            signature=signature,
        ):
            response = jsonify({"error": "invalid_signature"})
            response.status_code = 401
            return response

        def process_request():
            handler.handle(request)

        run_async(process_request)
        return "", 200

    @flask_app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"ok": True})

    return flask_app


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    application = create_app()
    application.run(host="0.0.0.0", port=3000, debug=True)
