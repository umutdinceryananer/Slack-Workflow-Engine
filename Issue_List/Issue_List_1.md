# Part 1 - MVP Issue List (18 items)

This list translates the Part-1 scope and lock decisions into actionable issues. Each item includes a brief description, concrete acceptance criteria, and explicit tests.

## Global Definition of Done (applies to all issues)
- Code follows the existing style and runs locally.
- Tests exist for the change and pass with `pytest -q`.
- Logs are JSON via structlog; no secrets/PII are logged.
- Errors return JSON with a correlation `trace_id` when applicable.

## 1) Project Scaffolding and Dependencies ✅
- Description: Set up a minimal Python project structure and dependencies required for MVP.
- Acceptance Criteria:
  - `app.py` (entry) and a minimal package/module layout exist.
  - Dependencies: `flask`, `slack_bolt`, `sqlalchemy`, `pydantic`, `structlog`.
  - Dev/test deps: `pytest` available; a minimal `requirements.txt` exists.
  - CI workflow at `.github/workflows/ci.yml` runs on `push` and `pull_request`, sets up Python `3.11`, installs `requirements.txt`, and runs `pytest -q`; pipeline passes on the default branch.
- Tests:
  - `pytest -q` discovers and runs a trivial smoke test.

## 2) Environment Configuration and .env.example ✅
- Description: Centralize configuration via environment variables and provide examples.
- Acceptance Criteria:
  - `.env.example` includes: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `APPROVER_USER_IDS`, `DATABASE_URL`.
  - `APPROVER_USER_IDS` format is comma-separated Slack user IDs and is parsed on startup.
  - Missing required env vars cause a clear startup error (fail fast).
- Tests:
  - Parametrized tests for missing/invalid env vars; parse of `APPROVER_USER_IDS`.
  
  Cross-References:
  - Extended by Part-2 #17 "RBAC: Roles, Role Members, and Config References" (role-based approvers and group sync env/config).
  - Extended by Part-2 #20 "Config Live Reload + Validation + Four-eyes Apply" (dynamic config governance).

## 3) Flask + Slack Bolt Integration ✅
- Description: Integrate Slack Bolt with Flask using `SlackRequestHandler` and expose routes.
- Acceptance Criteria:
  - Route `POST /slack/events` wired through Bolt handler.
  - Global error handler returns JSON with a `trace_id`.
  - Route `GET /healthz` reserved (empty impl acceptable until Issue 16).
- Tests:
  - App factory test: `/slack/events` exists; error handler produces JSON for an injected error.

## 4) Slack Signature Verification and Replay Protection ✅
- Description: Verify `X-Slack-Signature` and `X-Slack-Request-Timestamp` with a sliding time window.
- Acceptance Criteria:
  - Default time window 5 minutes; stale timestamp or invalid signature returns `401`.
  - Requests failing verification do not hit business handlers.
- Tests:
  - Valid/invalid signature and replay (same signature twice) cases.

## 5) 3-Second Ack and Async Processing ✅
- Description: Enforce Slack’s 3-second rule using immediate `ack()` and offload long work.
- Acceptance Criteria:
  - Shared utility for async execution (e.g., a small thread pool) used by slash/actions.
  - `ack()` is always called within 3 seconds in happy-path tests.
  - Async utility propagates `trace_id` to worker thread.
- Tests:
  - Handler under artificial delay still calls `ack()` within 3 seconds; `trace_id` propagation verified.

## 6) Workflow Config Schema (Pydantic) and Loader ? ✅
- Description: Define the schema for a workflow (refund) and load `workflows/refund.json` at startup.
- Acceptance Criteria:
  - Validation errors are logged and the app fails fast on invalid config.
  - Fields supported: `text`, `number`, `textarea`; `approvers.strategy`, `approvers.levels`, `notify_channel`.
  - Unknown workflow type yields a clear ephemeral error in slash handler.
- Tests:
  - Invalid config sample raises at startup; valid config loads and is accessible.

  Cross-References:
  - Extended by Part-2 #6 "Config Schema Extension for Multi-level Approvals" (sequential/parallel levels).

## 7) SQLAlchemy Models: requests and messages ✅
- Description: Implement minimal persistence for requests and message references.
- Acceptance Criteria:
  - `requests(id, type, created_by, payload_json, status, created_at, updated_at, decided_by, decided_at, request_key, version)`.
  - `messages(request_id, channel_id, ts, thread_ts)`.
  - Unique index on `request_key`.
  - DB initialization on startup (SQLite acceptable for MVP).
- Tests:
  - Schema creation test (`create_all`) ensures tables and unique index exist; round-trip insert/select works.

  Cross-References:
  - Extended by Part-2 #7 "State Machine: Levels + Quorum (N-of-M) + Tie-breaker" (adds `approvals` and `status_history` tables via Alembic).

## 8) State Machine and Optimistic Locking ✅
- Description: Encapsulate status transitions and prevent race/double-click effects.
- Acceptance Criteria:
  - Allowed transitions: `PENDING` -> `APPROVED|REJECTED`; error on invalid.
  - Concurrency guard using `version` or conditional update prevents duplicate decisions.
- Tests:
  - Concurrent decision attempts: only one succeeds; invalid transition raises.

## 9) Slash Command `/request refund` and Modal Builder
- Description: Register slash command and open a modal built from the config schema.
- Acceptance Criteria:
  - `/request refund` opens a modal with configured fields and `required` markers.
  - Errors reported via ephemeral message.
- Tests:
  - Block Kit snapshot for the modal; invalid type returns ephemeral error.

## 10) Modal Submission Validation and Persistence ✅
- Description: Validate submitted values with Pydantic and create a request record.
- Acceptance Criteria:
  - `payload_json` stored as canonical JSON (stable key order; trimmed values where applicable).
  - After creation, an ephemeral confirmation is sent to the submitter with a link to the channel message.
- Tests:
  - Canonicalization test for the generated `payload_json` and link presence in the ephemeral response.

## 11) Channel Message with Approve/Reject and Message Reference ✅
- Description: Post a Block Kit message to `notify_channel` with decision buttons; persist reference.
- Acceptance Criteria:
  - Message includes title, key fields, and Approve/Reject buttons.
  - `channel_id`, `ts`, `thread_ts` saved in `messages`.
- Tests:
  - Block Kit snapshot for the posted message; DB contains the `messages` record.

  Cross-References:
  - Extended by Part-2 #9 "Message Updates for Level Progress + Pending Approvers" (level progress and remaining approvers visibility).
  - Related to Part-2 #16 "Central Rate-limit/Retry Utility for Slack Calls" (robust publish/update wrapper).

## 12) Approve Action Handler (+ Authorization)
- Description: Handle Approve clicks, enforce approver list, update status and message.
- Acceptance Criteria:
  - User must be in `APPROVER_USER_IDS`; otherwise ephemeral "unauthorized" is shown.
  - Status becomes `APPROVED`; message reflects decision (badge/emoji/text) and buttons are disabled.
- Tests:
  - Authorized vs unauthorized user; message update snapshot includes disabled buttons.

  Cross-References:
  - Extended by Part-2 #4 "Home Quick Actions (Approve/Reject)" (actions from Home view).
  - Extended by Part-2 #7/#9 "Levels & Message Updates" (multi-level approvals and richer updates).
  - Related to Part-2 #10 "SLA/Timeout + Escalation per Level" and #11 "Delegation/Proxy/OOO".

## 13) Reject Action Handler (+ Authorization) ✅
- Description: Handle Reject clicks, enforce approver list, update status and message.
- Acceptance Criteria:
  - User must be in `APPROVER_USER_IDS`; otherwise ephemeral "unauthorized" is shown.
  - Status becomes `REJECTED`; message reflects decision (badge/emoji/text) and buttons are disabled.
- Tests:
  - Authorized vs unauthorized user; message update snapshot includes disabled buttons.

  Cross-References:
  - Extended by Part-2 #4 "Home Quick Actions (Approve/Reject)" (actions from Home view).
  - Extended by Part-2 #7/#9 "Levels & Message Updates" (multi-level approvals and richer updates).
  - Related to Part-2 #15 "Revise/Resubmit Cycle and Cancel/Rollback" (post-reject flows).
 
## E2E Manual Test (after Issue 13) ✅
- When to run: after Issue 10–13 are complete (slash → modal → persist → channel message → approve/reject).
- Slack App setup:
  - Create an app in your workspace; obtain Bot Token and Signing Secret.
  - Scopes: `commands`, `chat:write`, `views:open`, `views:write` (optionally `chat:write.public`).
  - Slash Command: `/request` → Request URL: `https://<ngrok>/slack/events`.
  - Interactivity URL: `https://<ngrok>/slack/events`.
  - Add the app to the target channel.
- Environment: set `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `APPROVER_USER_IDS`, `DATABASE_URL`.
- Run locally: `python app.py` and `ngrok http 3000`.
- Steps:
  - In Slack: `/request refund` → confirm the modal opens with configured fields.
  - Submit → verify DB insert and channel message posted (with Approve/Reject).
  - Click Approve/Reject → status and message are updated accordingly; buttons disabled.
- Troubleshooting:
  - `invalid_auth`: verify tokens and app installed to channel.
  - Signature mismatch: ensure ngrok URL matches Slack settings.
  - 3s ack warnings: app running; route reachable; ack occurs instantly.
 
## 14) Self-Approval Guard ✅
- Description: Prevent the request creator from approving or rejecting their own request.
- Acceptance Criteria:
  - Creator attempting Approve receives an ephemeral "cannot approve own request".
  - Creator attempting Reject receives an ephemeral "cannot reject own request".
- Tests:
  - Attempt by creator is rejected; non-creator approver succeeds.
  - Self-reject attempt is blocked; non-creator reject succeeds.

## 15) Idempotency (Requests and Actions)
- Description: Ensure duplicate submissions and repeated clicks do not create duplicate effects.
- Acceptance Criteria:
  - `request_key = sha256(type + user_id + canonical_payload)` unique index enforced.
  - Action dedup based on Slack action context (or stored last decision) prevents double-processing.
- Tests:
  - Duplicate modal submissions dedupe to the same request; duplicate action clicks processed once.

  Cross-References:
  - Extended by Part-2 #14 "Ordering and Deduplication Guarantees" (outbox/event-level idempotency and ordering).

## 16) Deep Healthcheck `/healthz`
- Description: Report application health including DB and config validity.
- Acceptance Criteria:
  - Returns `{ ok: true, db: "up", config: "valid", version: "x.y.z" }` on success; version read from a `VERSION` file or package metadata.
  - Returns non-200 and a clear JSON body on failure.
- Tests:
  - Healthy and failing scenarios (DB down, invalid config) return correct JSON and status codes.

  Cross-References:
  - Complements Part-2 #18 "Prometheus Metrics Endpoint (Phase-2)" (metrics exposed alongside health).

## 17) Structured Logging with Correlation
- Description: Log with `structlog` in JSON and include correlation fields.
- Acceptance Criteria:
  - Events: `request_created`, `approved`, `rejected`, `unauthorized_attempt`, `webhook_failed`.
  - Each log includes `trace_id` and, where applicable, `request_id`; secrets/PII are redacted.
- Tests:
  - Log capture asserts presence of fields and absence of secrets; correlation `trace_id` continuity across async boundary.

  Cross-References:
  - Extended by Part-2 #18 "Prometheus Metrics Endpoint (Phase-2)" (adds metrics beyond logs).

## 18) [Moved] Test Utilities and Snapshot Baseline
- This issue has been moved to Optional. See: `Development_Documents/Issue_List/Issue_List_Optional.md` (Part‑1 Optional #1).
