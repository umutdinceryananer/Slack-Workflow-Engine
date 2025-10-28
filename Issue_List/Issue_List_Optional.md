# Optional Issue List (Portfolio Enhancements)

This document collects items deferred from Part-1 and Part-2 to keep the core scope lean. Each entry lists a short description and suggested tests if you decide to build the enhancement later.

## Part-1 Optional #1 - Test Utilities and Snapshot Baseline
- From: Issue_List_1.md #18
- Scope: Shared test utilities, deterministic time freezing, and Block Kit snapshot helpers.
- Tests: Meta-tests covering time-freeze determinism and snapshot harness behaviour.

## Part-2 Optional #1 - Delegation/Proxy/OOO Handling
- From: Issue_List_2.md #11
- Scope: Proxy mapping so delegates can approve on behalf of primaries, with full auditing.
- Tests: Proxy vs non-proxy authorisation, audit log assertions, negative scenarios.

## Part-2 Optional #2 - Home Saved Filters
- From: Issue_List_2.md #5
- Scope: Persist user-specific saved filters for the Home view.
- Tests: CRUD tests for saved filters; Home snapshot showing the saved-filter badge.

## Part-2 Optional #3 - Cursor-based Pagination for Home
- From: Issue_List_2.md #3
- Scope: Replace offset pagination with cursor tokens for large Home lists.
- Tests: Query-layer token tests; Home payload snapshot reflecting cursors.

## Part-2 Optional #4 - Slack User Group Sync for RBAC
- From: Issue_List_2.md #17
- Scope: Sync Slack user groups into role membership with TTL caching and fail-closed behaviour.
- Tests: TTL/invalidation unit tests; API failure scenarios; membership resolution tests.

## Part-2 Optional #5 - Signed Link Export
- From: Issue_List_2.md #19
- Scope: Generate time-bound signed links for CSV/JSON exports.
- Tests: Signature validity/expiry tests; unauthorised access rejection.

## Part-2 Optional #6 - Config Live Reload Watcher + Four-eyes Apply
- From: Issue_List_2.md #20
- Scope: File watcher that detects config changes and enforces two-person approval before applying.
- Tests: File-change trigger, preview diff generation, double-confirm success, single-confirm failure.
