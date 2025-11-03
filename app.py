"""Application entry point for the Slack Workflow Engine MVP."""

from __future__ import annotations

import json
from uuid import uuid4

from flask import Flask, jsonify, request, copy_current_request_context
from pydantic import ValidationError
from slack_bolt import App as SlackApp
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.errors import SlackApiError

from slack_workflow_engine.actions import is_user_authorized, parse_action_context
from slack_workflow_engine.background import run_async
from slack_workflow_engine.config import AppSettings, get_settings
from slack_workflow_engine.db import session_scope
from slack_workflow_engine.models import (
    Request,
    StatusTransitionError,
    OptimisticLockError,
    advance_request_status,
)
from slack_workflow_engine.security import (
    SLACK_SIGNATURE_HEADER,
    SLACK_TIMESTAMP_HEADER,
    is_valid_slack_request,
)
from slack_workflow_engine.workflows import (
    WORKFLOW_DEFINITION_DIR,
    build_modal_view,
    APPROVE_ACTION_ID,
    REJECT_ACTION_ID,
)
from slack_workflow_engine.workflows.commands import parse_slash_command, load_workflow_or_raise
from slack_workflow_engine.workflows.notifications import (
    publish_request_message,
    update_request_message,
)
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
    print("[debug] Attempting to open modal", trigger_id, workflow_type)
    try:
        client.views_open(trigger_id=trigger_id, view=view)
        print("[debug] Modal opened OK")
    except SlackApiError as exc:  # pragma: no cover - network dependent
        print("[debug] Modal open failed:", exc.response.get("error"))
        logger.error(
            "Failed to open workflow modal",
            extra={"workflow_type": workflow_type, "error": exc.response.get("error")},
        )


def _handle_request_command(ack, command, client, logger):
    print("[debug] Slash payload:", command)
    try:
        context = parse_slash_command(command.get("text") or "")
        print("[debug] Parsed workflow_type:", context.workflow_type)
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
    print("[debug] Trigger ID:", trigger_id)
    ack()
    run_async(_open_modal, client, trigger_id, view, context.workflow_type, logger)


def _register_slash_handlers(bolt_app: SlackApp) -> None:
    WORKFLOW_DEFINITION_DIR.mkdir(parents=True, exist_ok=True)

    @bolt_app.command("/request")
    def handle_request(ack, command, client, logger):
        _handle_request_command(ack=ack, command=command, client=client, logger=logger)


def _handle_view_submission(ack, body, client, logger):
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
    request = save_request(
        workflow_type=workflow_type,
        created_by=user_id,
        payload_json=canonical_payload,
        request_key=request_key,
    )

    ack({"response_action": "clear"})
    run_async(
        publish_request_message,
        client=client,
        definition=definition,
        submission=submission,
        request_id=request.id,
        logger=logger,
    )


def _register_view_handlers(bolt_app: SlackApp) -> None:
    @bolt_app.view("workflow_submit")
    def handle_submission(ack, body, client, logger):
        _handle_view_submission(ack=ack, body=body, client=client, logger=logger)


def _extract_action_reason(body: dict) -> str | None:
    values = body.get("state", {}).get("values", {})
    for block in values.values():
        if not isinstance(block, dict):
            continue
        for control in block.values():
            if not isinstance(control, dict):
                continue
            value = control.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
            selected = control.get("selected_option")
            if isinstance(selected, dict):
                selected_value = selected.get("value")
                if isinstance(selected_value, str) and selected_value.strip():
                    return selected_value.strip()
    return None


def _handle_approve_action(ack, body, client, logger):
    actions = body.get("actions") or []
    try:
        action_payload = actions[0]
    except IndexError:
        ack({"response_type": "ephemeral", "text": "Unable to process this action payload."})
        return

    try:
        context = parse_action_context(action_payload.get("value", ""))
    except ValueError:
        ack({"response_type": "ephemeral", "text": "This action payload is invalid. Please retry from Slack."})
        return

    user_id = body.get("user", {}).get("id")
    if not user_id:
        ack({"response_type": "ephemeral", "text": "We could not identify the acting user."})
        return

    settings = get_settings()
    if not is_user_authorized(user_id, settings.approver_user_ids):
        ack({"response_type": "ephemeral", "text": "You are not authorized to approve this request."})
        return

    submission_payload = ""
    channel_id = ""
    ts = ""
    with session_scope() as session:
        request = session.get(Request, context.request_id)
        if request is None:
            ack({"response_type": "ephemeral", "text": "Request could not be found."})
            return

        if request.type != context.workflow_type:
            ack({"response_type": "ephemeral", "text": "Workflow type mismatch for this request."})
            return

        message = request.message
        if message is None:
            ack({"response_type": "ephemeral", "text": "Request message is not yet available."})
            return

        submission_payload = request.payload_json
        channel_id = message.channel_id
        ts = message.ts

        try:
            advance_request_status(
                session,
                request,
                new_status="APPROVED",
                decided_by=user_id,
            )
        except StatusTransitionError:
            ack({"response_type": "ephemeral", "text": "This request has already been decided."})
            return
        except OptimisticLockError:
            ack({"response_type": "ephemeral", "text": "Request was updated concurrently. Please try again."})
            return

    ack({"response_type": "ephemeral", "text": "Request approved."})

    try:
        definition = load_workflow_or_raise(context.workflow_type)
    except (FileNotFoundError, ValidationError):
        logger.exception(
            "Unable to load workflow definition during approval",
            extra={"workflow_type": context.workflow_type},
        )
        return

    try:
        submission = json.loads(submission_payload) if submission_payload else {}
    except json.JSONDecodeError:
        logger.exception(
            "Stored payload_json is invalid JSON",
            extra={"request_id": context.request_id},
        )
        submission = {}

    run_async(
        update_request_message,
        client=client,
        definition=definition,
        submission=submission,
        request_id=context.request_id,
        decision="APPROVED",
        decided_by=user_id,
        channel_id=channel_id,
        ts=ts,
        logger=logger,
    )


def _handle_reject_action(ack, body, client, logger):
    actions = body.get("actions") or []
    try:
        action_payload = actions[0]
    except IndexError:
        ack({"response_type": "ephemeral", "text": "Unable to process this action payload."})
        return

    try:
        context = parse_action_context(action_payload.get("value", ""))
    except ValueError:
        ack({"response_type": "ephemeral", "text": "This action payload is invalid. Please retry from Slack."})
        return

    user_id = body.get("user", {}).get("id")
    if not user_id:
        ack({"response_type": "ephemeral", "text": "We could not identify the acting user."})
        return

    settings = get_settings()
    if not is_user_authorized(user_id, settings.approver_user_ids):
        ack({"response_type": "ephemeral", "text": "You are not authorized to reject this request."})
        return

    submission_payload = ""
    channel_id = ""
    ts = ""
    reason = _extract_action_reason(body)
    with session_scope() as session:
        request = session.get(Request, context.request_id)
        if request is None:
            ack({"response_type": "ephemeral", "text": "Request could not be found."})
            return

        if request.type != context.workflow_type:
            ack({"response_type": "ephemeral", "text": "Workflow type mismatch for this request."})
            return

        message = request.message
        if message is None:
            ack({"response_type": "ephemeral", "text": "Request message is not yet available."})
            return

        submission_payload = request.payload_json
        channel_id = message.channel_id
        ts = message.ts

        try:
            advance_request_status(
                session,
                request,
                new_status="REJECTED",
                decided_by=user_id,
            )
        except StatusTransitionError:
            ack({"response_type": "ephemeral", "text": "This request has already been decided."})
            return
        except OptimisticLockError:
            ack({"response_type": "ephemeral", "text": "Request was updated concurrently. Please try again."})
            return

    ack({"response_type": "ephemeral", "text": "Request rejected."})

    try:
        definition = load_workflow_or_raise(context.workflow_type)
    except (FileNotFoundError, ValidationError):
        logger.exception(
            "Unable to load workflow definition during rejection",
            extra={"workflow_type": context.workflow_type},
        )
        return

    try:
        submission = json.loads(submission_payload) if submission_payload else {}
    except json.JSONDecodeError:
        logger.exception(
            "Stored payload_json is invalid JSON",
            extra={"request_id": context.request_id},
        )
        submission = {}

    run_async(
        update_request_message,
        client=client,
        definition=definition,
        submission=submission,
        request_id=context.request_id,
        decision="REJECTED",
        decided_by=user_id,
        channel_id=channel_id,
        ts=ts,
        logger=logger,
        reason=reason,
    )


def _register_action_handlers(bolt_app: SlackApp) -> None:
    @bolt_app.action(APPROVE_ACTION_ID)
    def handle_approve(ack, body, client, logger):
        _handle_approve_action(ack=ack, body=body, client=client, logger=logger)

    @bolt_app.action(REJECT_ACTION_ID)
    def handle_reject(ack, body, client, logger):
        _handle_reject_action(ack=ack, body=body, client=client, logger=logger)


def create_app() -> Flask:
    """Create and configure the Flask application."""

    settings = get_settings()
    bolt_app = _create_bolt_app(settings)
    handler = SlackRequestHandler(bolt_app)
    flask_app = Flask(__name__)
    flask_app.logger.setLevel("INFO")

    _register_error_handlers(flask_app)
    _register_slash_handlers(bolt_app)
    _register_view_handlers(bolt_app)
    _register_action_handlers(bolt_app)

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        raw_body = request.get_data(as_text=True)
        timestamp = request.headers.get(SLACK_TIMESTAMP_HEADER, "")
        signature = request.headers.get(SLACK_SIGNATURE_HEADER, "")
        print("[debug] Incoming /slack/events headers:", dict(request.headers))
        print("[debug] Incoming /slack/events body:", raw_body)
        if not is_valid_slack_request(
            signing_secret=settings.signing_secret,
            timestamp=timestamp,
            body=raw_body,
            signature=signature,
        ):
            response = jsonify({"error": "invalid_signature"})
            response.status_code = 401
            return response

        @copy_current_request_context
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
    application.run(host="0.0.0.0", port=3000, debug=False, use_reloader=False)
