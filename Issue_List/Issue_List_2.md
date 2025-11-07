# Part 2 - Phase 2 Issue List (20 items)

This list translates Part-2 (Home Tab, multi-level approvals, webhooks, RBAC, observability, admin) into actionable issues. Each item includes acceptance criteria and explicit tests.

## Global Definition of Done (applies to all issues)
- Code runs locally; style consistent with the repo.
- Tests exist and pass with `pytest -q` (unit/snapshot where relevant).
- Logs are structured JSON via structlog; no secrets/PII in logs.
- Errors return JSON with a correlation `trace_id` when applicable.

## 1) App Home Foundation + Debounced Publish ✅ 
- Description: Handle `app_home_opened`, assemble Home view, and publish with debouncing to respect rate limits.
- Acceptance Criteria:
  - `app_home_opened` event handler registered.
  - Debounce logic prevents redundant `views.publish` within a short window per user.
  - Basic Home shell renders with sections/placeholders.
- Tests:
  - Snapshot of initial Home payload; debounce unit test verifies single publish for rapid repeats.

## 2) Home Lists: My Requests + Pending Approvals ✅
- Description: Show the user’s last N created requests and items awaiting their approval.
- Acceptance Criteria:
  - "My Requests" (latest 10) and "Awaiting My Approval" sections render from DB.
  - Empty-state messages shown when lists are empty.
- Tests:
  - DB-backed fetch functions unit-tested; Home payload snapshot with populated and empty states.

## 3) Home Filters/Sort + Pagination (offset-based) ✅
- Description: Add filter by type/status/date; sort; simple offset-based pagination.
- Acceptance Criteria:
  - Filter chips or section toggles for type/status/date.
  - Offset/limit parameters supported; next/prev controls.
- Tests:
  - Query-layer tests for filters/sort/offset pagination; snapshot reflects filter application.

## 4) Home Quick Actions (Approve/Reject) ✅
- Description: Enable Approve/Reject directly from Home for eligible approvers.
- Acceptance Criteria:
  - Blocks include action buttons only for authorized users.
  - Decisions from Home update DB and refresh the view.
  - Decision flow supports reason capture (Reject requires a reason; Approve reason optional) and optional attachment link.
  - Captured reason/attachment are persisted (see `approvals` table in Issue 7).
- Tests:
  - Authorized vs unauthorized action tests; snapshot after decision shows updated state.
  - Reason requirement enforced for Reject; optional attachment accepted and persisted.

## 5) Home Search
- Description: Quick text search.
- Acceptance Criteria:
  - Text search across request id/title/fields.
- Tests:
  - Search index function tests; filter application reflected in Home snapshot.
- Manual verification:
  - Open App Home, enter a workflow keyword (e.g. `refund`) in the search field, and confirm both sections filter to matching requests.
  - Search by requester (Slack user ID) and numeric request ID to confirm all supported dimensions work.
  - Clear the search box to reset results, then trigger an Approve/Reject quick action and verify the view refreshes with the search term reapplied.

## 6) Config Schema Extension for Multi-level Approvals ✅
- Description: Extend workflow config to support `approvers.strategy` (sequential/parallel) and `approvers.levels`.
- Acceptance Criteria:
  - Pydantic schema updated; validation errors are clear.
  - Example config added/updated for refund.
- Tests:
  - Valid/invalid config samples; schema rejects malformed levels.

## 7) State Machine: Levels + Quorum (N-of-M) + Tie-breaker
- Description: Add level-based states (e.g., `PENDING_L1`, `PENDING_L2`) and parallel quorum rules.
- Acceptance Criteria:
  - Sequential and parallel flows supported; quorum threshold configurable.
  - Tie-breaker policy defined and enforced when needed.
  - DB tables exist for auditability: `approvals(request_id, level, approver_id, decision, reason, attachment_url, decided_at)` and `status_history(request_id, from_status, to_status, at, by)`.
  - Alembic baseline and an initial migration create these tables.
- Tests:
  - Parallel approvals reach quorum; sequential progresses level by level; tie-breaker scenario covered.
  - Migration test applies Alembic baseline and verifies tables/columns present.

## 8) Level-based Authorization and Action Visibility
- Description: Only approvers of the active level can see/trigger actions.
- Acceptance Criteria:
  - Authorization gate checks level eligibility; others see no action buttons.
- Tests:
  - Eligible/ineligible user cases; message snapshot hides buttons for ineligible users.

## 9) Message Updates for Level Progress + Pending Approvers
- Description: Update channel message to reflect current level, remaining approvers, and disable controls post decision.
- Acceptance Criteria:
  - Block Kit updated on each level change; remaining approvers listed.
  - After final decision, buttons disabled and final status shown.
  - Decisions include the provided reason (and attachment link, if any) in the message or a thread reply.
  - After any decision (from channel or Home), impacted users’ Home views are refreshed.
- Tests:
  - Snapshot tests for transitions (L1 -> L2 -> final); disabled buttons verified.
  - Reason/attachment presence asserted in message or thread; Home refresh trigger invoked once per decision.

## 10) SLA/Timeout + Escalation per Level
- Description: Configure per-level SLA; on timeout, escalate to fallback (user/role) and annotate the record.
- Acceptance Criteria:
  - Scheduler/cron-like mechanism triggers SLA checks.
  - Escalation posts a note (thread or DM) and updates metadata.
  - Escalation is idempotent and triggers at most once per level.
- Tests:
  - Time-frozen tests: before/after SLA threshold; escalation action executed once.
  - Duplicate scheduler runs do not create duplicate escalations.

## 11) [Moved] Delegation/Proxy/OOO Handling
- This issue has been moved to Optional. See: `Development_Documents/Issue_List/Issue_List_Optional.md` (Part‑2 Optional #1).

## 12) Webhook Outbox Model + HMAC Contract
- Description: Define `outbox(event, endpoint, payload_json, status, attempts, next_attempt_at, idempotency_key)` and HMAC signing.
- Acceptance Criteria:
  - Outbox record created on terminal events; HMAC (shared secret) added to headers.
  - Contract version included in payload.
  - Allowed statuses include `PENDING`, `SENT`, `FAILED`, `DEAD_LETTER`.
- Tests:
  - Outbox record creation; HMAC signature generation/verification unit test.

## 13) Webhook Dispatcher with Retry/Backoff + Manual Replay
- Description: Worker processes outbox with exponential backoff; manual replay endpoint exists.
- Acceptance Criteria:
  - Retries on 5xx/network errors; honors `Retry-After`/429.
  - Manual replay endpoint limited to admins.
  - After max attempts, mark record as `DEAD_LETTER`; manual replay moves it back to `PENDING`.
- Tests:
  - Simulated 5xx/429 with backoff scheduling; manual replay re-enqueues correctly.
  - After exceeding max attempts status becomes `DEAD_LETTER` and is respected until manual replay.

## 14) Ordering and Deduplication Guarantees
- Description: Guarantee per-request ordering and endpoint-level idempotency.
- Acceptance Criteria:
  - Idempotency key combines request id + endpoint + event version.
  - Dispatcher respects ordering for the same request.
- Tests:
  - Out-of-order enqueues still deliver in-order; duplicate items processed once.

## 15) Revise/Resubmit Cycle and Cancel/Rollback
- Description: Support "Rejected → Revised → Re-review" and request cancel; guard rollback of decisions with clear rules.
- Acceptance Criteria:
  - New `REVISED` path reopens the flow (level reset policy defined).
  - Cancel marks request and disables further actions; rollback rules documented and enforced.
- Tests:
  - Revise path resets to expected level; cancel prevents further actions; rollback denied when forbidden.

## 16) Central Rate-limit/Retry Utility for Slack Calls
- Description: Centralize Slack API 429/backoff and transient retry handling.
- Acceptance Criteria:
  - Shared wrapper for Slack client calls with exponential backoff and `Retry-After` handling.
  - All message publish/update paths use the wrapper.
- Tests:
  - Simulated 429/backoff; verifies limited retries and eventual success/failure behavior.

## 17) RBAC: Roles, Role Members, and Config References
- Description: Add `roles` and `role_members`, allow config approvers to reference roles, and admin commands.
- Acceptance Criteria:
  - Tables created; `/workflow roles list/add/remove` commands implemented.
  - Start with static DB roles and manual membership.
- Tests:
  - Role CRUD; mapping users to roles; command handlers.
  - Note: Slack user group sync is optional (see Optional #4).

## 18) Prometheus Metrics Endpoint (Phase-2)
- Description: Expose application metrics for requests and approvals.
- Acceptance Criteria:
  - Counters: `requests_total`, `approvals_total`, `webhook_retries_total`.
  - Histogram: `approval_latency_seconds` with sensible buckets.
  - Scraped by Part-3 Issue #12 via ServiceMonitor (no additional endpoint required).
- Tests:
  - Metrics endpoint returns expected names; counters/histogram change after test actions.

## 19) Reporting & Export (CSV/JSON)
- Description: Export filtered requests as CSV/JSON with selectable columns.
- Acceptance Criteria:
  - Filters align with Home filters; sensitive fields are excluded or masked.
  - Admin-only download endpoint; no signed links.
- Tests:
  - Export includes selected columns; sanitized output; access control enforced.

## 20) Config Reload + Validation (manual)
- Description: Provide a manual reload endpoint/command; validate changes before apply.
- Acceptance Criteria:
  - Admin command triggers reload; invalid config rejected with clear errors.
  - Preview shows diff (basic); single admin confirmation applies.
  - Immutable audit trail entry written for preview and apply (who, when, diff, outcome).
- Tests:
  - Manual reload validation; preview diff generated; apply succeeds with admin confirmation.
  - Audit log entries exist with actor, timestamp, diff, and result.
