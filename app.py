"""Application entry point for the Slack Workflow Engine MVP."""

from __future__ import annotations

import json
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
)
from slack_workflow_engine.workflows.commands import parse_slash_command, load_workflow_or_raise
from slack_workflow_engine.workflows.requests import (
    canonical_json,
    compute_request_key,
    parse_submission,
)
from slack_workflow_engine.workflows.storage import save_request


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


def _open_modal(client, trigger_id: str, view: dict, workflow_type: str, logger) -> None:
    try:
        client.views_open(trigger_id=trigger_id, view=view)
    except SlackApiError as exc:  # pragma: no cover - network dependent
        logger.error(
            "Failed to open workflow modal",
            extra={"workflow_type": workflow_type, "error": exc.response.get("error")},
        )


def _handle_request_command(ack, command, client, logger):
    try:
        context = parse_slash_command(command.get("text") or "")
    except ValueError as exc:
        ack({"response_type": "ephemeral", "text": str(exc)})
        return

    try:
        definition = load_workflow_or_raise(context.workflow_type)
    except FileNotFoundError:
        ack({"response_type": "ephemeral", "text": f"Workflow `{context.workflow_type}` is not configured."})
        return
    except ValidationError:
        logger.exception("Invalid workflow definition", extra={"workflow_type": context.workflow_type})
        ack({"response_type": "ephemeral", "text": "This workflow definition is invalid. Please contact an administrator."})
        return

    view = build_modal_view(definition)
    trigger_id = command.get("trigger_id")
    ack()
    run_async(_open_modal, client, trigger_id, view, context.workflow_type, logger)


def _register_slash_handlers(bolt_app: SlackApp) -> None:
    WORKFLOW_DEFINITION_DIR.mkdir(parents=True, exist_ok=True)

    @bolt_app.command("/request")
    def handle_request(ack, command, client, logger):
        _handle_request_command(ack=ack, command=command, client=client, logger=logger)


def _handle_view_submission(ack, body, logger):
    view = body.get("view", {})
    metadata_raw = view.get("private_metadata", "{}")
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        ack({"response_action": "errors", "errors": {"general": "Invalid workflow metadata."}})
        return

    workflow_type = metadata.get("workflow_type")
    if not workflow_type:
        ack({"response_action": "errors", "errors": {"general": "Workflow metadata missing."}})
        return

    try:
        definition = load_workflow_or_raise(workflow_type)
    except FileNotFoundError:
        ack({"response_action": "errors", "errors": {"general": "Workflow configuration not found."}})
        return
    except ValidationError:
        logger.exception("Invalid workflow definition during submission", extra={"workflow_type": workflow_type})
        ack({"response_action": "errors", "errors": {"general": "Workflow definition invalid."}})
        return

    state_payload = {"values": view.get("state", {}).get("values", {})}
    try:
        submission = parse_submission(state_payload, definition)
    except ValueError as exc:
        message = str(exc)
        block = "general"
        if ":" in message:
            block, message = message.split(":", 1)
            block = block.strip()
            message = message.strip()
        ack({"response_action": "errors", "errors": {block: message}})
        return

    user_id = body.get("user", {}).get("id", "unknown")
    canonical_payload = canonical_json(submission)
    request_key = compute_request_key(workflow_type, user_id, canonical_payload)
    save_request(
        workflow_type=workflow_type,
        created_by=user_id,
        payload_json=canonical_payload,
        request_key=request_key,
    )

    ack({"response_action": "clear"})


def _register_view_handlers(bolt_app: SlackApp) -> None:
    @bolt_app.view("workflow_submit")
    def handle_submission(ack, body, logger):
        _handle_view_submission(ack=ack, body=body, logger=logger)


def create_app() -> Flask:
    """Create and configure the Flask application."""

    settings = get_settings()
    bolt_app = _create_bolt_app(settings)
    handler = SlackRequestHandler(bolt_app)
    flask_app = Flask(__name__)

    _register_error_handlers(flask_app)
    _register_slash_handlers(bolt_app)
    _register_view_handlers(bolt_app)

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
