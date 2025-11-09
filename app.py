"""Application entry point for the Slack Workflow Engine MVP."""































































from __future__ import annotations

from dataclasses import dataclass































































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
    HOME_SEARCH_ACTION_ID,
    HOME_SEARCH_BLOCK_ID,
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
































from slack_workflow_engine.workflows.state import (
    compute_level_runtime,
    derive_initial_status,
    extract_level_from_status,
    format_status_text,
    is_pending_status,
    pending_status,
)

from slack_workflow_engine.workflows.storage import save_request

HOME_DEBOUNCER = HomeDebouncer()



def _compute_home_filters(settings: AppSettings, *, query: str | None = None):
    request_filters = normalise_filters(
        sort_by="created_at",
        sort_order="desc",
        limit=settings.home_recent_limit,
        default_limit=settings.home_recent_limit,
        query=query,
    )
    pending_filters = normalise_filters(
        statuses=("PENDING",),
        sort_by="created_at",
        sort_order="asc",
        limit=settings.home_pending_limit,
        default_limit=settings.home_pending_limit,
        query=query,
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

    @bolt_app.action(HOME_SEARCH_ACTION_ID)
    def handle_home_search(ack, body, client, logger):

        _handle_home_search_action(ack=ack, body=body, client=client, logger=logger)

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



        initial_status = derive_initial_status(definition)

        try:

            request = save_request(

                workflow_type=workflow_type,

                created_by=user_id,

                payload_json=canonical_payload,

                request_key=request_key,

                status=initial_status,

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



        runtime = compute_level_runtime(
            definition=definition,
            status=initial_status,
            decisions=[],
        )
        status_text = format_status_text(runtime)
        ack({"response_action": "clear"})

        run_async(
            publish_request_message,
            client=client,
            definition=definition,
            submission=submission,
            request_id=request.id,
            logger=logger,
            trace_id=trace_id,
            approver_level=extract_level_from_status(initial_status),
            status_text=status_text,
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
    level: int = 1,
) -> None:

    cleaned_reason = (reason or "").strip() or None
    cleaned_attachment = (attachment_url or "").strip() or None
    decided_at = datetime.now(UTC)

    existing = (
        session.query(ApprovalDecision)
        .filter(
            ApprovalDecision.request_id == request.id,
            ApprovalDecision.level == level,
            ApprovalDecision.decided_by == decided_by,
        )
        .one_or_none()
    )

    if existing is None:
        session.add(
            ApprovalDecision(
                request_id=request.id,
                level=level,
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
    existing.level = level
    existing.decided_by = decided_by
    existing.decided_at = decided_at
    existing.reason = cleaned_reason
    existing.attachment_url = cleaned_attachment
    existing.source = source


class LevelPermissionError(Exception):
    """Raised when an approver attempts to act on a level they are not assigned to."""


@dataclass(frozen=True)
class DecisionResult:
    final_decision: str | None
    status_text: str
    approver_level: int | None
    include_actions: bool
    waiting_on: list[str]


def _load_level_decisions(session, *, request_id: int, level: int | None) -> list[ApprovalDecision]:
    if not level:
        return []
    return (
        session.query(ApprovalDecision)
        .filter(ApprovalDecision.request_id == request_id, ApprovalDecision.level == level)
        .all()
    )


def _build_status_text(
    *,
    session,
    definition: WorkflowDefinition,
    request: Request,
) -> str:
    level = extract_level_from_status(request.status)
    decisions = _load_level_decisions(session, request_id=request.id, level=level)
    runtime = compute_level_runtime(definition=definition, status=request.status, decisions=decisions)
    return format_status_text(runtime)


def _apply_level_decision(
    session,
    *,
    request: Request,
    definition: WorkflowDefinition,
    user_id: str,
    decision: str,
    source: str,
    reason: str | None,
    attachment_url: str | None,
) -> DecisionResult:
    if not is_pending_status(request.status):
        raise StatusTransitionError(f"Request {request.id} is no longer pending.")

    level_index = extract_level_from_status(request.status) or 1
    level_decisions = _load_level_decisions(session, request_id=request.id, level=level_index)
    runtime_before = compute_level_runtime(definition=definition, status=request.status, decisions=level_decisions)
    if runtime_before.level is None:
        raise StatusTransitionError(f"Request {request.id} has no actionable levels.")

    if user_id not in runtime_before.waiting_on:
        raise LevelPermissionError("This request is not waiting on your decision.")

    level_def = definition.approvers.levels[level_index - 1]
    awaiting_tie = runtime_before.awaiting_tie_breaker
    tie_breaker_acting = awaiting_tie and level_def.tie_breaker == user_id

    _record_approval_decision(
        session,
        request=request,
        decision=decision,
        decided_by=user_id,
        reason=reason,
        attachment_url=attachment_url,
        source=source,
        level=level_index,
    )
    session.flush()

    level_decisions = _load_level_decisions(session, request_id=request.id, level=level_index)
    runtime_after = compute_level_runtime(definition=definition, status=request.status, decisions=level_decisions)

    final_decision: str | None = None
    include_actions = True
    level_completed = False
    quorum = runtime_after.quorum or len(level_def.members)

    if decision == "REJECTED":
        if tie_breaker_acting or not awaiting_tie:
            final_decision = "REJECTED"
            include_actions = False
    elif tie_breaker_acting and decision == "APPROVED":
        level_completed = True
    elif runtime_after.approvals >= quorum:
        level_completed = True
    elif runtime_after.rejections > 0 and not awaiting_tie:
        final_decision = "REJECTED"
        include_actions = False

    if not final_decision and not level_completed:
        if not runtime_after.waiting_on and not runtime_after.awaiting_tie_breaker:
            final_decision = "REJECTED"
            include_actions = False

    if final_decision == "REJECTED":
        advance_request_status(session, request, new_status="REJECTED", decided_by=user_id)
    elif level_completed:
        if level_index >= len(definition.approvers.levels):
            advance_request_status(session, request, new_status="APPROVED", decided_by=user_id)
            final_decision = "APPROVED"
            include_actions = False
        else:
            next_status = pending_status(level_index + 1)
            advance_request_status(session, request, new_status=next_status, decided_by=user_id)

    post_level = extract_level_from_status(request.status)
    post_decisions = _load_level_decisions(session, request_id=request.id, level=post_level)
    post_runtime = compute_level_runtime(
        definition=definition,
        status=request.status,
        decisions=post_decisions,
    )
    status_text = format_status_text(post_runtime)
    approver_level = post_runtime.level if include_actions else None

    return DecisionResult(
        final_decision=final_decision,
        status_text=status_text,
        approver_level=approver_level,
        include_actions=include_actions,
        waiting_on=list(post_runtime.waiting_on),
    )































































































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

        attachment_url = _extract_attachment_url(body)

        try:
            definition = load_workflow_or_raise(context.workflow_type)
        except (FileNotFoundError, ValidationError):
            logger.exception(
                "Unable to load workflow definition during approval",
                extra={"workflow_type": context.workflow_type},
            )
            ack({"response_type": "ephemeral", "text": "Workflow definition invalid."})
            return

        submission_payload = ""
        channel_id = ""
        ts = ""
        request_owner = ""
        result = None

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

            active_level = extract_level_from_status(request.status)
            if context.level is not None and active_level is not None and context.level != active_level:
                ack({"response_type": "ephemeral", "text": "This request advanced to a new level. Please refresh and try again."})
                log.info("level_mismatch", payload_level=context.level, current_level=active_level)
                return

            submission_payload = request.payload_json
            channel_id = message.channel_id
            ts = message.ts
            request_owner = request.created_by
            log = log.bind(message_channel=channel_id)

            try:
                result = _apply_level_decision(
                    session,
                    request=request,
                    definition=definition,
                    user_id=user_id,
                    decision="APPROVED",
                    source="channel",
                    reason=None,
                    attachment_url=attachment_url,
                )
            except LevelPermissionError:
                ack({"response_type": "ephemeral", "text": "This request is not currently waiting on you."})
                log.info("level_not_waiting", user_id=user_id)
                return
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

        if result is None:
            ack({"response_type": "ephemeral", "text": "Unable to record this approval."})
            log.warning("approval_result_missing", user_id=user_id)
            return

        ack({"response_type": "ephemeral", "text": "Request approved."})
        log.info("approved", decided_by=user_id)

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
            decided_by=user_id,
            channel_id=channel_id,
            ts=ts,
            logger=logger,
            decision=result.final_decision,
            reason=None,
            attachment_url=attachment_url if result.final_decision else None,
            status_text=result.status_text,
            approver_level=result.approver_level,
            include_actions=result.include_actions,
            trace_id=trace_id,
        )

        refresh_targets = {user_id, request_owner}
        refresh_targets.update(result.waiting_on or [])

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids=refresh_targets,
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

        reason = _extract_action_reason(body)
        attachment_url = _extract_attachment_url(body)

        try:
            definition = load_workflow_or_raise(context.workflow_type)
        except (FileNotFoundError, ValidationError):
            logger.exception(
                "Unable to load workflow definition during rejection",
                extra={"workflow_type": context.workflow_type},
            )
            ack({"response_type": "ephemeral", "text": "Workflow definition invalid."})
            return

        submission_payload = ""
        channel_id = ""
        ts = ""
        request_owner = ""
        result = None

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

            active_level = extract_level_from_status(request.status)
            if context.level is not None and active_level is not None and context.level != active_level:
                ack({"response_type": "ephemeral", "text": "This request advanced to a new level. Please refresh and try again."})
                log.info("level_mismatch", payload_level=context.level, current_level=active_level)
                return

            submission_payload = request.payload_json
            channel_id = message.channel_id
            ts = message.ts
            request_owner = request.created_by
            log = log.bind(message_channel=channel_id)

            try:
                result = _apply_level_decision(
                    session,
                    request=request,
                    definition=definition,
                    user_id=user_id,
                    decision="REJECTED",
                    source="channel",
                    reason=reason,
                    attachment_url=attachment_url,
                )
            except LevelPermissionError:
                ack({"response_type": "ephemeral", "text": "This request is not currently waiting on you."})
                log.info("level_not_waiting", user_id=user_id)
                return
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

        if result is None:
            ack({"response_type": "ephemeral", "text": "Unable to record this rejection."})
            log.warning("rejection_result_missing", user_id=user_id)
            return

        ack({"response_type": "ephemeral", "text": "Request rejected."})
        log.info("rejected", decided_by=user_id, reason=reason or None)

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
            decided_by=user_id,
            channel_id=channel_id,
            ts=ts,
            logger=logger,
            decision=result.final_decision,
            reason=reason if result.final_decision == "REJECTED" else None,
            attachment_url=attachment_url if result.final_decision else None,
            status_text=result.status_text,
            approver_level=result.approver_level,
            include_actions=result.include_actions,
            trace_id=trace_id,
        )

        refresh_targets = {user_id, request_owner}
        refresh_targets.update(result.waiting_on or [])

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids=refresh_targets,
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

        modal_level = None

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

            try:

                definition = load_workflow_or_raise(request.type)

            except (FileNotFoundError, ValidationError):

                _ack_home_error(ack, block_id, "Workflow definition invalid. Please contact an admin.")

                log.warning("home_definition_load_failed", request_type=request.type)

                return

            if request.created_by == user_id:

                _ack_home_error(ack, block_id, "You cannot approve your own request.")

                log.info("home_self_action_blocked", user_id=user_id)

                return

            if not is_pending_status(request.status):

                _ack_home_error(ack, block_id, "This request has already been decided.")

                log.info("home_decision_already_recorded", request_status=request.status, user_id=user_id)

                return

            active_level = extract_level_from_status(request.status)

            if context.level is not None and active_level is not None and context.level != active_level:

                _ack_home_error(ack, block_id, "This request moved to another level. Please refresh and try again.")

                log.info("home_level_mismatch", payload_level=context.level, current_level=active_level)

                return

            decisions = _load_level_decisions(session, request_id=request.id, level=active_level)

            runtime = compute_level_runtime(
                definition=definition,
                status=request.status,
                decisions=decisions,
            )

            if runtime.level is None or user_id not in runtime.waiting_on:

                _ack_home_error(ack, block_id, "This request is not currently waiting on you.")

                log.info("home_not_waiting", user_id=user_id)

                return

            modal_level = runtime.level

        trigger_id = body.get("trigger_id")

        if not trigger_id:

            _ack_home_error(ack, block_id, "We could not open a confirmation modal. Please try again.")

            log.warning("home_action_missing_trigger", user_id=user_id)

            return

        modal_view = build_home_decision_modal(
            decision=decision,
            request_id=context.request_id,
            workflow_type=context.workflow_type,
            level=modal_level,
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


def _handle_home_search_action(ack, body, client, logger):

    trace_id = str(uuid4())

    bind_contextvars(trace_id=trace_id)

    log = structlog.get_logger().bind(trace_id=trace_id)

    try:

        actions = body.get("actions") or []

        if not actions:

            ack(
                {
                    "response_action": "errors",
                    "errors": {
                        HOME_SEARCH_BLOCK_ID: "Enter a search term to continue.",
                    },
                }
            )

            log.warning("home_search_missing_payload")

            return

        action_payload = actions[0]

        raw_query = action_payload.get("value", "")

        query = raw_query.strip() if isinstance(raw_query, str) else ""

        user_id = body.get("user", {}).get("id")

        if not user_id:

            ack(
                {
                    "response_action": "errors",
                    "errors": {
                        HOME_SEARCH_BLOCK_ID: "We could not identify the acting user.",
                    },
                }
            )

            log.warning("home_search_missing_user")

            return

        ack()

        settings = get_settings()

        request_filters, pending_filters = _compute_home_filters(settings, query=query or None)

        view, recent_count, pending_count = _prepare_home_view(
            user_id=user_id,
            request_filters=request_filters,
            pending_filters=pending_filters,
        )

        HOME_DEBOUNCER.clear(user_id)

        log.info(
            "home_search_performed",
            user_id=user_id,
            query=query or None,
            recent_count=recent_count,
            pending_count=pending_count,
        )

        client.views_publish(user_id=user_id, view=view)

    except SlackApiError as exc:

        error_code = exc.response.get("error") if getattr(exc, "response", None) else str(exc)

        log.error("home_search_publish_failed", error=error_code)

        logger.error(
            "Failed to publish App Home search view",
            extra={"user_id": body.get("user", {}).get("id"), "error": error_code},
        )

    finally:

        unbind_contextvars("trace_id")


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

        metadata_level = metadata.get("level")

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

        try:

            definition = load_workflow_or_raise(workflow_type)

        except (FileNotFoundError, ValidationError):

            ack({"response_action": "errors", "errors": {"general": "Workflow definition invalid. Please contact an admin."}})

            log.warning("home_decision_definition_missing", workflow_type=workflow_type)

            return

        submission_payload = ""

        channel_id = ""

        ts = ""

        request_owner = ""

        result = None

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

            if not is_pending_status(request.status):

                ack({"response_action": "errors", "errors": {"general": "This request has already been decided."}})

                log.info("home_decision_already_recorded", request_status=request.status)

                return

            message = request.message

            if message is None:

                ack({"response_action": "errors", "errors": {"general": "Request message is not yet available."}})

                log.warning("home_decision_message_missing", user_id=user_id)

                return

            active_level = extract_level_from_status(request.status)

            if metadata_level is not None and active_level is not None and metadata_level != active_level:

                ack({"response_action": "errors", "errors": {"general": "This request moved to another level. Please refresh and try again."}})

                log.info("home_decision_level_mismatch", payload_level=metadata_level, current_level=active_level)

                return

            submission_payload = request.payload_json

            channel_id = message.channel_id

            ts = message.ts

            request_owner = request.created_by

            log = log.bind(message_channel=channel_id)

            try:

                result = _apply_level_decision(
                    session,
                    request=request,
                    definition=definition,
                    user_id=user_id,
                    decision=decision,
                    source="home",
                    reason=reason,
                    attachment_url=attachment_url,
                )

            except LevelPermissionError:

                ack({"response_action": "errors", "errors": {"general": "This request is not currently waiting on you."}})

                log.info("home_decision_not_waiting", user_id=user_id)

                return

            except StatusTransitionError:

                ack({"response_action": "errors", "errors": {"general": "This request has already been decided."}})

                log.info("home_decision_race", user_id=user_id)

                return

            except OptimisticLockError:

                ack({"response_action": "errors", "errors": {"general": "Request was updated concurrently. Please try again."}})

                log.warning("home_decision_optimistic_lock_failed", user_id=user_id)

                return

        if result is None:

            ack({"response_action": "errors", "errors": {"general": "Unable to record this decision."}})

            log.warning("home_decision_result_missing", user_id=user_id)

            return

        ack({"response_action": "clear"})

        log.info("home_decision_recorded", user_id=user_id)

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
            decided_by=user_id,
            channel_id=channel_id,
            ts=ts,
            logger=logger,
            decision=result.final_decision,
            reason=reason if result.final_decision == "REJECTED" else None,
            attachment_url=attachment_url if result.final_decision else None,
            status_text=result.status_text,
            approver_level=result.approver_level,
            include_actions=result.include_actions,
            trace_id=trace_id,
        )

        refresh_targets = {user_id, request_owner}

        refresh_targets.update(result.waiting_on or [])

        _schedule_home_refresh(
            client=client,
            logger=logger,
            user_ids=refresh_targets,
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



