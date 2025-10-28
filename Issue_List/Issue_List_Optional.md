# Optional Issue List (Portfolio Enhancements)

This file collects items deferred from Part‑1 and Part‑2 to keep the core scope lean. Each item includes a brief scope and expected tests if implemented later.

## Part‑1 Optional #1 — Test Utilities and Snapshot Baseline
- From: Issue_List_1.md #18 (moved)
- Description: Shared test utilities, fixtures, deterministic time freezing, and snapshot helpers for Block Kit payloads.
- Acceptance Criteria:
  - Time freezing helper present; reusable mock Slack client utilities.
  - Snapshot harness to compare Block Kit structures across changes.
- Tests:
  - Meta‑tests verify time freeze determinism and snapshot harness operation.

## Part‑2 Optional #1 — Delegation/Proxy/OOO Handling
- From: Issue_List_2.md #11 (moved)
- Description: Proxy mapping to allow delegates to approve on behalf of primaries; full audit.
- Acceptance Criteria:
  - Proxy map (env/config/DB) enforced; audit log records proxy actor and principal.
  - UI clearly indicates proxy actions; security constraints documented.
- Tests:
  - Proxy vs non‑proxy authorization; audit log assertions; negative cases.

## Part‑2 Optional #2 — Home Saved Filters
- From: Issue_List_2.md #5 (split)
- Description: Persist user‑specific saved filters for Home view.
- Acceptance Criteria:
  - CRUD for saved filters; default “last used” restored on open.
- Tests:
  - CRUD tests; Home snapshot includes saved filter badge/indicator.

## Part‑2 Optional #3 — Cursor‑based Pagination for Home
- From: Issue_List_2.md #3 (split)
- Description: Replace offset pagination with cursor tokens for large lists.
- Acceptance Criteria:
  - Cursor tokens supported; stable sort key; back/forward navigation.
- Tests:
  - Query layer token tests; Home payload snapshot reflects cursors.

## Part‑2 Optional #4 — Slack User Group Sync for RBAC
- From: Issue_List_2.md #17 (split)
- Description: Sync Slack user groups into role membership with TTL cache and fail‑closed semantics.
- Acceptance Criteria:
  - Scheduled sync; TTL invalidation; error handling operates fail‑closed.
- Tests:
  - TTL/invalidation unit tests; API failure scenarios; membership resolution tests.

## Part‑2 Optional #5 — Signed Link Export
- From: Issue_List_2.md #19 (split)
- Description: Generate time‑bound signed links for CSV/JSON exports.
- Acceptance Criteria:
  - Signed URL generation with expiry and scope; download endpoint validates signature.
- Tests:
  - Signature validity/expiry tests; unauthorized use rejected.

## Part‑2 Optional #6 — Config Live Reload Watcher + Four‑eyes Apply
- From: Issue_List_2.md #20 (split)
- Description: File watcher to auto‑detect config changes and two‑person approval to apply diffs.
- Acceptance Criteria:
  - Watcher detects changes; preview diff shown; apply requires two distinct admins.
- Tests:
  - File change triggers preview; double‑confirm apply passes; single‑confirm fails.

