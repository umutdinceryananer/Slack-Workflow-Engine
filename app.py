"""Application entry point for the Slack Workflow Engine MVP."""































































from __future__ import annotations































































import json































from pathlib import Path































from uuid import uuid4
from datetime import UTC, datetime
from urllib.parse import urlparse






























































from flask import Flask, jsonify, request, copy_current_request_context































from pydantic import ValidationError































from slack_bolt import App as SlackApp































from slack_bolt.adapter.flask import SlackRequestHandler































from slack_sdk.errors import SlackApiError































from sqlalchemy import text































import structlog
from structlog.contextvars import bind_contextvars, unbind_contextvars






























































from slack_workflow_engine.actions import is_user_authorized, parse_action_context































from slack_workflow_engine.background import run_async































from slack_workflow_engine.config import AppSettings, get_settings































from slack_workflow_engine.db import session_scope































from slack_workflow_engine.models import (
    Request,
    StatusTransitionError,
    OptimisticLockError,
    DuplicateRequestError,
    ApprovalDecision,
    advance_request_status,
)































from slack_workflow_engine.logging_config import configure_logging
from slack_workflow_engine.home import (
    HomeDebouncer,
    PaginationState,
    HOME_APPROVE_ACTION_ID,
    HOME_REJECT_ACTION_ID,
    HOME_DECISION_MODAL_CALLBACK_ID,
    HOME_REASON_BLOCK_ID,
    HOME_ATTACHMENT_BLOCK_ID,
    build_home_placeholder_view,
    build_home_view,
    build_home_decision_modal,
    list_pending_approvals,
    list_recent_requests,
    normalise_filters,
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

HOME_DEBOUNCER = HomeDebouncer()



def _compute_home_filters(settings: AppSettings):
    request_filters = normalise_filters(
        sort_by="created_at",
        sort_order="desc",
        limit=settings.home_recent_limit,
        default_limit=settings.home_recent_limit,
    )
    pending_filters = normalise_filters(
        statuses=("PENDING",),
        sort_by="created_at",
        sort_order="asc",
        limit=settings.home_pending_limit,
        default_limit=settings.home_pending_limit,
    )
    return request_filters, pending_filters



def _prepare_home_view(*, user_id: str | None, request_filters, pending_filters):
    with session_scope() as session:
        my_requests = list_recent_requests(
            session,
            user_id=user_id or "",
            workflow_types=request_filters.workflow_types,
            statuses=request_filters.statuses,
            start_at=request_filters.start_at,
            end_at=request_filters.end_at,
            sort_by=request_filters.sort_by,
            sort_order=request_filters.sort_order,
            limit=request_filters.limit + 1,
            offset=request_filters.offset,
            query=request_filters.query,
        )
        pending = list_pending_approvals(
            session,
            approver_id=user_id or "",
            workflow_types=pending_filters.workflow_types,
            statuses=pending_filters.statuses,
            start_at=pending_filters.start_at,
            end_at=pending_filters.end_at,
            sort_by=pending_filters.sort_by,
            sort_order=pending_filters.sort_order,
            limit=pending_filters.limit + 1,
            offset=pending_filters.offset,
            query=pending_filters.query,
        )

    my_has_more = len(my_requests) > request_filters.limit
    if my_has_more:
        my_requests = my_requests[: request_filters.limit]

    pending_has_more = len(pending) > pending_filters.limit
    if pending_has_more:
        pending = pending[: pending_filters.limit]

    my_pagination = PaginationState(
        offset=request_filters.offset,
        limit=request_filters.limit,
        has_previous=request_filters.offset > 0,
        has_more=my_has_more,
    )

    pending_pagination = PaginationState(
        offset=pending_filters.offset,
        limit=pending_filters.limit,
        has_previous=pending_filters.offset > 0,
        has_more=pending_has_more,
    )

    view = build_home_view(
        my_requests=my_requests,
        pending_approvals=pending,
        my_filters=request_filters,
        pending_filters=pending_filters,
        my_pagination=my_pagination,
        pending_pagination=pending_pagination,
    )

    return view, len(my_requests), len(pending)



def _refresh_home_tabs(*, client, user_ids, logger, trace_id: str | None = None):
    if not user_ids:
        return

    settings = get_settings()
    request_filters, pending_filters = _compute_home_filters(settings)
    log = structlog.get_logger()
    if trace_id:
        log = log.bind(trace_id=trace_id)
    seen: set[str] = set()

    for user_id in user_ids:
        if not user_id or user_id in seen:
            continue

        seen.add(user_id)
        HOME_DEBOUNCER.clear(user_id)

        try:
            view, recent_count, pending_count = _prepare_home_view(
                user_id=user_id,
                request_filters=request_filters,
                pending_filters=pending_filters,
            )
        except Exception:
            logger.exception(
                "Failed to prepare App Home view during refresh",
                extra={"user_id": user_id},
            )
            continue

        try:
            client.views_publish(user_id=user_id, view=view)
        except SlackApiError as exc:
            error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)
            log.warning("home_refresh_failed", user_id=user_id, error=error_code)
            logger.warning(
                "Failed to publish App Home view during refresh",
                extra={"user_id": user_id, "error": error_code},
            )
            continue

        log.info(
            "home_refresh_published",
            user_id=user_id,
            recent_count=recent_count,
            pending_count=pending_count,
        )


def _schedule_home_refresh(*, client, logger, user_ids, trace_id: str | None = None) -> None:
    targets = [user_id for user_id in set(user_ids) if user_id]
    if not targets:
        return

    run_async(
        _refresh_home_tabs,
        client=client,
        user_ids=targets,
        logger=logger,
        trace_id=trace_id,
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































































































def _open_modal(client, trigger_id: str, view: dict, workflow_type: str, logger, trace_id: str | None = None) -> None:































    logger.info("Attempting to open modal", extra={"workflow_type": workflow_type})































    try:































        client.views_open(trigger_id=trigger_id, view=view)































        logger.info("Modal open call succeeded", extra={"workflow_type": workflow_type})































    except SlackApiError as exc:  # pragma: no cover - network dependent































        logger.error(































            "Failed to open workflow modal",































            extra={































                "workflow_type": workflow_type,































                "error": exc.response.get("error"),































                "response": exc.response.data,































            },































        )































































































def _handle_app_home_opened(event, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    user_id = (event or {}).get("user")

    log = log.bind(user_id=user_id)

    try:

        log.info("app_home_opened")

        if not HOME_DEBOUNCER.should_publish(user_id):

            log.info("app_home_publish_skipped", reason="debounced")

            return

        settings = get_settings()
        request_filters, pending_filters = _compute_home_filters(settings)

        view, recent_count, pending_count = _prepare_home_view(
            user_id=user_id,
            request_filters=request_filters,
            pending_filters=pending_filters,
        )

        log.info("app_home_data_prepared", recent_count=recent_count, pending_count=pending_count)

        client.views_publish(user_id=user_id, view=view)

        log.info("app_home_publish_requested")

    except SlackApiError as exc:

        status_code = getattr(exc.response, "status_code", None) if getattr(exc, "response", None) else None

        error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)

        log.error("app_home_publish_failed", error=error_code, status_code=status_code)

        logger.error(

            "Failed to publish App Home view",

            extra={

                "user_id": user_id,

                "error": error_code,

                "status_code": status_code,

            },

        )

    finally:

        unbind_contextvars("trace_id")


def _handle_request_command(ack, command, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

        workflow_text = (command.get("text") or "").strip()

        log.info(

            "slash_command_received",

            command=command.get("command"),

            workflow_type=workflow_text,

        )



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

            logger.exception(

                "Invalid workflow definition",

                extra={"workflow_type": context.workflow_type},

            )

            ack({"response_type": "ephemeral", "text": "This workflow definition is invalid. Please contact an administrator."})

            return



        view = build_modal_view(definition)

        trigger_id = command.get("trigger_id")

        ack()

        run_async(
            _open_modal,
            client,
            trigger_id,
            view,
            context.workflow_type,
            logger,
            trace_id=trace_id,
        )
    finally:

        unbind_contextvars("trace_id")

def _register_home_handlers(bolt_app: SlackApp) -> None:

    @bolt_app.event("app_home_opened")
    def handle_app_home(event, client, logger):

        _handle_app_home_opened(event=event, client=client, logger=logger)


def _register_slash_handlers(bolt_app: SlackApp) -> None:































    WORKFLOW_DEFINITION_DIR.mkdir(parents=True, exist_ok=True)































































    @bolt_app.command("/request")































    def handle_request(ack, command, client, logger):































        _handle_request_command(ack=ack, command=command, client=client, logger=logger)































































































def _handle_view_submission(ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

        view = body.get("view", {})

        metadata_raw = view.get("private_metadata", "{}")

        try:

            metadata = json.loads(metadata_raw)

        except json.JSONDecodeError:

            ack({"response_action": "errors", "errors": {"general": "Invalid workflow metadata."}})

            return



        workflow_type = metadata.get("workflow_type")

        log = log.bind(workflow_type=workflow_type)

        if not workflow_type:

            ack({"response_action": "errors", "errors": {"general": "Workflow metadata missing."}})

            return



        try:

            definition = load_workflow_or_raise(workflow_type)

        except FileNotFoundError:

            ack({"response_action": "errors", "errors": {"general": "Workflow configuration not found."}})

            return

        except ValidationError:

            logger.exception(

                "Invalid workflow definition during submission",

                extra={"workflow_type": workflow_type},

            )

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



        try:

            request = save_request(

                workflow_type=workflow_type,

                created_by=user_id,

                payload_json=canonical_payload,

                request_key=request_key,

            )

            log.info("request_created", request_id=request.id, user_id=user_id)

        except DuplicateRequestError:

            ack(

                {

                    "response_action": "errors",

                    "errors": {

                        definition.fields[0].name if definition.fields else "general": "You already submitted this request."

                    },

                }

            )

            return



        ack({"response_action": "clear"})

        run_async(
            publish_request_message,
            client=client,
            definition=definition,
            submission=submission,
            request_id=request.id,
            logger=logger,
            trace_id=trace_id,
        )
    finally:

        unbind_contextvars("trace_id")

def _register_view_handlers(bolt_app: SlackApp) -> None:































    @bolt_app.view("workflow_submit")































    def handle_submission(ack, body, client, logger):































        _handle_view_submission(ack=ack, body=body, client=client, logger=logger)

    @bolt_app.view(HOME_DECISION_MODAL_CALLBACK_ID)

    def handle_home_decision_modal(ack, body, client, logger):

        _handle_home_decision_submission(ack=ack, body=body, client=client, logger=logger)































































































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


def _extract_attachment_url(body: dict) -> str | None:

    values = body.get("state", {}).get("values", {})

    block = values.get(HOME_ATTACHMENT_BLOCK_ID)

    if not isinstance(block, dict):

        return None

    for control in block.values():

        if not isinstance(control, dict):

            continue

        value = control.get("value")

        if isinstance(value, str):

            trimmed = value.strip()

            if trimmed:

                return trimmed

    return None


def _validate_attachment_url(url: str | None) -> bool:

    if not url:

        return True

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):

        return False

    if not parsed.netloc:

        return False

    return True


def _record_approval_decision(
    session,
    *,
    request: Request,
    decision: str,
    decided_by: str,
    reason: str | None,
    attachment_url: str | None,
    source: str,
) -> None:

    cleaned_reason = (reason or "").strip() or None

    cleaned_attachment = (attachment_url or "").strip() or None

    decided_at = request.decided_at or datetime.now(UTC)

    existing = request.approvals[0] if request.approvals else None

    if existing is None:

        session.add(
            ApprovalDecision(
                request_id=request.id,
                decision=decision,
                decided_by=decided_by,
                decided_at=decided_at,
                reason=cleaned_reason,
                attachment_url=cleaned_attachment,
                source=source,
            )
        )

        return

    existing.decision = decision
    existing.decided_by = decided_by
    existing.decided_at = decided_at
    existing.reason = cleaned_reason
    existing.attachment_url = cleaned_attachment
    existing.source = source































































































def _handle_approve_action(ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

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

            log.warning("invalid_action_payload")

            return



        log = log.bind(request_id=context.request_id, workflow_type=context.workflow_type)



        user_id = body.get("user", {}).get("id")

        if not user_id:

            ack({"response_type": "ephemeral", "text": "We could not identify the acting user."})

            log.warning("missing_user_id")

            return



        settings = get_settings()

        if not is_user_authorized(user_id, settings.approver_user_ids):

            ack()

            channel_id = body.get("channel", {}).get("id")

            if channel_id:

                client.chat_postEphemeral(

                    channel=channel_id,

                    user=user_id,

                    text="You are not authorized to approve this request.",

                )

            log.warning("unauthorized_attempt", user_id=user_id)

            return



        submission_payload = ""

        channel_id = ""

        ts = ""

        attachment_url = _extract_attachment_url(body)

        request_owner = ""

        with session_scope() as session:

            request = session.get(Request, context.request_id)

            if request is None:

                ack({"response_type": "ephemeral", "text": "Request could not be found."})

                log.warning("request_missing", user_id=user_id)

                return



            if request.type != context.workflow_type:

                ack({"response_type": "ephemeral", "text": "Workflow type mismatch for this request."})

                log.warning("workflow_type_mismatch", request_type=request.type, expected=context.workflow_type)

                return



            message = request.message

            if message is None:

                ack({"response_type": "ephemeral", "text": "Request message is not yet available."})

                log.warning("message_reference_missing", user_id=user_id)

                return



            if request.created_by == user_id:

                ack()

                client.chat_postEphemeral(

                    channel=message.channel_id,

                    user=user_id,

                    text="You cannot approve your own request.",

                )

                log.info("self_approval_blocked", user_id=user_id)

                return



            submission_payload = request.payload_json

            channel_id = message.channel_id

            ts = message.ts

            request_owner = request.created_by

            log = log.bind(message_channel=channel_id)



            try:

                advance_request_status(

                    session,

                    request,

                    new_status="APPROVED",

                    decided_by=user_id,

                )

                _record_approval_decision(
                    session,
                    request=request,
                    decision="APPROVED",
                    decided_by=user_id,
                    reason=None,
                    attachment_url=attachment_url,
                    source="channel",
                )

            except StatusTransitionError:

                ack()

                client.chat_postEphemeral(

                    channel=message.channel_id,

                    user=user_id,

                    text="This request has already been decided.",

                )

                log.info("decision_already_recorded", user_id=user_id, decision=request.status)

                return

            except OptimisticLockError:

                ack({"response_type": "ephemeral", "text": "Request was updated concurrently. Please try again."})

                log.warning("optimistic_lock_failed", user_id=user_id)

                return



        ack({"response_type": "ephemeral", "text": "Request approved."})
        log.info("approved", decided_by=user_id)


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
        attachment_url=attachment_url,
        trace_id=trace_id,
    )

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids={user_id, request_owner},
            trace_id=trace_id,
        )
    finally:

        unbind_contextvars("trace_id")

def _handle_reject_action(ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

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

            log.warning("invalid_action_payload")

            return



        log = log.bind(request_id=context.request_id, workflow_type=context.workflow_type)



        user_id = body.get("user", {}).get("id")

        if not user_id:

            ack({"response_type": "ephemeral", "text": "We could not identify the acting user."})

            log.warning("missing_user_id")

            return



        settings = get_settings()

        if not is_user_authorized(user_id, settings.approver_user_ids):

            ack()

            channel_id = body.get("channel", {}).get("id")

            if channel_id:

                client.chat_postEphemeral(

                    channel=channel_id,

                    user=user_id,

                    text="You are not authorized to reject this request.",

                )

            log.warning("unauthorized_attempt", user_id=user_id)

            return



        submission_payload = ""

        channel_id = ""

        ts = ""

        reason = _extract_action_reason(body)
        attachment_url = _extract_attachment_url(body)

        request_owner = ""

        with session_scope() as session:

            request = session.get(Request, context.request_id)

            if request is None:

                ack({"response_type": "ephemeral", "text": "Request could not be found."})

                log.warning("request_missing", user_id=user_id)

                return



            if request.type != context.workflow_type:

                ack({"response_type": "ephemeral", "text": "Workflow type mismatch for this request."})

                log.warning("workflow_type_mismatch", request_type=request.type, expected=context.workflow_type)

                return



            message = request.message

            if message is None:

                ack({"response_type": "ephemeral", "text": "Request message is not yet available."})

                log.warning("message_reference_missing", user_id=user_id)

                return



            if request.created_by == user_id:

                ack()

                client.chat_postEphemeral(

                    channel=message.channel_id,

                    user=user_id,

                    text="You cannot reject your own request.",

                )

                log.info("self_reject_blocked", user_id=user_id)

                return



            submission_payload = request.payload_json

            channel_id = message.channel_id

            ts = message.ts

            request_owner = request.created_by

            log = log.bind(message_channel=channel_id)



            try:

                advance_request_status(

                    session,

                    request,

                    new_status="REJECTED",

                    decided_by=user_id,

                )

                _record_approval_decision(
                    session,
                    request=request,
                    decision="REJECTED",
                    decided_by=user_id,
                    reason=reason,
                    attachment_url=attachment_url,
                    source="channel",
                )

            except StatusTransitionError:

                ack()

                client.chat_postEphemeral(

                    channel=message.channel_id,

                    user=user_id,

                    text="This request has already been decided.",

                )

                log.info("decision_already_recorded", user_id=user_id, decision=request.status)

                return

            except OptimisticLockError:

                ack({"response_type": "ephemeral", "text": "Request was updated concurrently. Please try again."})

                log.warning("optimistic_lock_failed", user_id=user_id)

                return



        ack({"response_type": "ephemeral", "text": "Request rejected."})
        log.info("rejected", decided_by=user_id, reason=reason or None)


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
        attachment_url=attachment_url,
        trace_id=trace_id,
    )

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids={user_id, request_owner},
            trace_id=trace_id,
        )
    finally:

        unbind_contextvars("trace_id")


def _ack_home_error(ack, block_id: str | None, message: str) -> None:

    target = block_id or "home_action_error"

    ack(
        {
            "response_action": "errors",
            "errors": {
                target: message,
            },
        }
    )


def _handle_home_action(decision: str, ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

        actions = body.get("actions") or []

        if not actions:

            _ack_home_error(ack, None, "Unable to process this action payload.")

            log.warning("home_action_missing_payload")

            return

        action_payload = actions[0]

        block_id = action_payload.get("block_id") or "home_action"

        try:

            context = parse_action_context(action_payload.get("value", ""))

        except ValueError:

            _ack_home_error(ack, block_id, "This action payload is invalid. Please refresh and try again.")

            log.warning("invalid_home_action_payload")

            return

        log = log.bind(request_id=context.request_id, workflow_type=context.workflow_type)

        user_id = body.get("user", {}).get("id")

        if not user_id:

            _ack_home_error(ack, block_id, "We could not identify the acting user.")

            log.warning("home_action_missing_user")

            return

        settings = get_settings()

        if not is_user_authorized(user_id, settings.approver_user_ids):

            _ack_home_error(ack, block_id, "You are not authorized to take action on this request.")

            log.warning("unauthorized_home_attempt", user_id=user_id)

            return

        with session_scope() as session:

            request = session.get(Request, context.request_id)

            if request is None:

                _ack_home_error(ack, block_id, "Request could not be found.")

                log.warning("home_request_missing", user_id=user_id)

                return

            if request.type != context.workflow_type:

                _ack_home_error(ack, block_id, "Workflow type mismatch for this request.")

                log.warning("home_workflow_type_mismatch", request_type=request.type)

                return

            if request.created_by == user_id:

                _ack_home_error(ack, block_id, "You cannot approve your own request.")

                log.info("home_self_action_blocked", user_id=user_id)

                return

            if request.status != "PENDING":

                _ack_home_error(ack, block_id, "This request has already been decided.")

                log.info("home_decision_already_recorded", request_status=request.status, user_id=user_id)

                return

        trigger_id = body.get("trigger_id")

        if not trigger_id:

            _ack_home_error(ack, block_id, "We could not open a confirmation modal. Please try again.")

            log.warning("home_action_missing_trigger", user_id=user_id)

            return

        modal_view = build_home_decision_modal(
            decision=decision,
            request_id=context.request_id,
            workflow_type=context.workflow_type,
        )

        ack()

        try:

            client.views_open(trigger_id=trigger_id, view=modal_view)

        except SlackApiError as exc:

            error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)

            log.error("home_decision_modal_open_failed", error=error_code)

            return

        log.info("home_decision_modal_opened", decision=decision, user_id=user_id)

    finally:

        unbind_contextvars("trace_id")


def _handle_home_approve_action(ack, body, client, logger):

    _handle_home_action("APPROVED", ack, body, client, logger)


def _handle_home_reject_action(ack, body, client, logger):

    _handle_home_action("REJECTED", ack, body, client, logger)


def _handle_home_decision_submission(ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

        view = body.get("view", {})

        metadata_raw = view.get("private_metadata", "{}")

        try:

            metadata = json.loads(metadata_raw)

        except json.JSONDecodeError:

            ack({"response_action": "errors", "errors": {"general": "Decision metadata is invalid."}})

            log.warning("home_decision_invalid_metadata")

            return

        decision = str(metadata.get("decision", "")).upper()

        request_id = metadata.get("request_id")

        workflow_type = metadata.get("workflow_type")

        log = log.bind(request_id=request_id, workflow_type=workflow_type, decision=decision)

        if decision not in {"APPROVED", "REJECTED"} or not request_id or not workflow_type:

            ack({"response_action": "errors", "errors": {"general": "Decision metadata is incomplete. Please try again."}})

            log.warning("home_decision_missing_metadata")

            return

        user_id = body.get("user", {}).get("id")

        if not user_id:

            ack({"response_action": "errors", "errors": {"general": "We could not identify the acting user."}})

            log.warning("home_decision_missing_user")

            return

        settings = get_settings()

        if not is_user_authorized(user_id, settings.approver_user_ids):

            ack({"response_action": "errors", "errors": {"general": "You are not authorized to take action on this request."}})

            log.warning("unauthorized_home_submission", user_id=user_id)

            return

        state_wrapper = {"state": {"values": view.get("state", {}).get("values", {})}}

        reason = _extract_action_reason(state_wrapper)

        attachment_url = _extract_attachment_url(state_wrapper)

        if decision == "REJECTED" and not reason:

            ack({"response_action": "errors", "errors": {HOME_REASON_BLOCK_ID: "Please provide a rejection reason."}})

            log.info("home_decision_missing_reason", user_id=user_id)

            return

        if attachment_url and not _validate_attachment_url(attachment_url):

            ack(
                {
                    "response_action": "errors",
                    "errors": {HOME_ATTACHMENT_BLOCK_ID: "Enter a valid URL starting with http or https."},
                }
            )

            log.info("home_decision_invalid_attachment", user_id=user_id)

            return

        submission_payload = ""

        channel_id = ""

        ts = ""

        request_owner = ""

        with session_scope() as session:

            request = session.get(Request, request_id)

            if request is None:

                ack({"response_action": "errors", "errors": {"general": "Request could not be found."}})

                log.warning("home_decision_request_missing", user_id=user_id)

                return

            if request.type != workflow_type:

                ack({"response_action": "errors", "errors": {"general": "Workflow type mismatch for this request."}})

                log.warning("home_decision_type_mismatch", request_type=request.type)

                return

            if request.created_by == user_id:

                ack({"response_action": "errors", "errors": {"general": "You cannot decide on your own request."}})

                log.info("home_decision_self_blocked", user_id=user_id)

                return

            if request.status != "PENDING":

                ack({"response_action": "errors", "errors": {"general": "This request has already been decided."}})

                log.info("home_decision_already_recorded", request_status=request.status)

                return

            message = request.message

            if message is None:

                ack({"response_action": "errors", "errors": {"general": "Request message is not yet available."}})

                log.warning("home_decision_message_missing")

                return

            submission_payload = request.payload_json

            channel_id = message.channel_id

            ts = message.ts

            request_owner = request.created_by

            try:

                advance_request_status(

                    session,

                    request,

                    new_status=decision,

                    decided_by=user_id,

                )

            except StatusTransitionError:

                ack({"response_action": "errors", "errors": {"general": "This request has already been decided."}})

                log.info("home_decision_status_transition_conflict", request_status=request.status)

                return

            except OptimisticLockError:

                ack(
                    {
                        "response_action": "errors",
                        "errors": {"general": "Request was updated concurrently. Please try again."},
                    }
                )

                log.warning("home_decision_optimistic_lock_failed")

                return

            _record_approval_decision(

                session,

                request=request,

                decision=decision,

                decided_by=user_id,

                reason=reason,

                attachment_url=attachment_url,

                source="home",

            )

        ack({"response_action": "clear"})

        log.info("home_decision_recorded", user_id=user_id)

        try:

            definition = load_workflow_or_raise(workflow_type)

        except (FileNotFoundError, ValidationError):

            logger.exception(

                "Unable to load workflow definition during home decision",

                extra={"workflow_type": workflow_type},

            )

            return

        try:

            submission = json.loads(submission_payload) if submission_payload else {}

        except json.JSONDecodeError:

            logger.exception(

                "Stored payload_json is invalid JSON",

                extra={"request_id": request_id},

            )

            submission = {}

        run_async(
            update_request_message,
            client=client,
            definition=definition,
            submission=submission,
            request_id=request_id,
            decision=decision,
            decided_by=user_id,
            channel_id=channel_id,
            ts=ts,
            logger=logger,
            reason=reason,
            attachment_url=attachment_url,
            trace_id=trace_id,
        )

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids={user_id, request_owner},
            trace_id=trace_id,
        )

    finally:

        unbind_contextvars("trace_id")


def _register_action_handlers(bolt_app: SlackApp) -> None:































    @bolt_app.action(APPROVE_ACTION_ID)































    def handle_approve(ack, body, client, logger):































        _handle_approve_action(ack=ack, body=body, client=client, logger=logger)































































    @bolt_app.action(REJECT_ACTION_ID)































    def handle_reject(ack, body, client, logger):































        _handle_reject_action(ack=ack, body=body, client=client, logger=logger)


    @bolt_app.action(HOME_APPROVE_ACTION_ID)
    def handle_home_approve(ack, body, client, logger):

        _handle_home_approve_action(ack=ack, body=body, client=client, logger=logger)


    @bolt_app.action(HOME_REJECT_ACTION_ID)
    def handle_home_reject(ack, body, client, logger):

        _handle_home_reject_action(ack=ack, body=body, client=client, logger=logger)































































































_LOGGING_CONFIGURED = False































































































def _load_version() -> str:































    version_file = Path(__file__).resolve().parent / "VERSION"































    if version_file.exists():































        return version_file.read_text(encoding="utf-8").strip()































    return "unknown"































































































def create_app() -> Flask:































    """Create and configure the Flask application."""































































    global _LOGGING_CONFIGURED































    if not _LOGGING_CONFIGURED:































        configure_logging()































        _LOGGING_CONFIGURED = True































































    settings = get_settings()































    bolt_app = _create_bolt_app(settings)































    handler = SlackRequestHandler(bolt_app)































    flask_app = Flask(__name__)































    flask_app.config["APP_VERSION"] = _load_version()































    flask_app.logger.setLevel("INFO")































































    _register_error_handlers(flask_app)

    _register_home_handlers(bolt_app)






























    _register_slash_handlers(bolt_app)































    _register_view_handlers(bolt_app)































    _register_action_handlers(bolt_app)































































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































































        trace_id = str(uuid4())
        @copy_current_request_context






























        def process_request():































            handler.handle(request)































































        run_async(process_request, trace_id=trace_id)






























        return "", 200































































    @flask_app.route("/healthz", methods=["GET"])































    def healthz():































        health: dict[str, object] = {"ok": True}































        health["version"] = flask_app.config.get("APP_VERSION", "unknown")































































        try:































            get_settings()































            health["config"] = "valid"































        except Exception as exc:  # pragma: no cover - defensive guard































            health["config"] = "invalid"































            health["config_error"] = str(exc)































            health["ok"] = False































































        try:































            with session_scope() as session:































                session.execute(text("SELECT 1"))































            health["db"] = "up"































        except Exception as exc:































            health["db"] = "down"































            health["db_error"] = str(exc)































            health["ok"] = False































































        status = 200 if health["ok"] else 503































        return jsonify(health), status































































    return flask_app































































































if __name__ == "__main__":  # pragma: no cover - manual execution helper































    application = create_app()































    application.run(host="0.0.0.0", port=3000, debug=True)
















