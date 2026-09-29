# Authored GC push checkpoint — 2026-09-30

This is local implementation and fixture qualification. No real FCM/APNs call,
production deployment, production migration or real Codex handoff was performed.

## Implemented boundary

- `create_gc_push_draft` requires `mcp:change` and creates a new draft through the
  existing website's `save_notification_draft` service. The explicit agency must
  be active; selected groups are limited to ten. Website title, body, group
  uniqueness and ownership rules apply. An existing draft cannot be overwritten.
- `prepare_gc_push` requires `mcp:communicate`, a saved draft ID and its expected
  revision. The ten-minute saved preview freezes content, group labels, recipient
  names and exact principal/grant signatures, and eligible device identities.
  Limits are ten selected groups, 100 people, 300 registrations and 1,000 source
  membership rows. Exceeding a limit rejects the whole preview without truncation.
- `confirm_gc_push` accepts only the plan ID and its exact lowercase SHA-256 hash.
  It rechecks current content, audience and devices, then calls the existing
  `send_notification` transaction to create the batch and native/in-app outbox.
  It adds retained MCP origin markers and exact device targets atomically. The
  initial queue receipt remains immutable across retries and later observations.
- `inspect_gc_push` reports the saved preview and separate current recipient and
  device counts. Raw push tokens, encrypted tokens and token lookup hashes are
  absent from the public preview and audit metadata. Device hashes are retained
  privately to detect token changes, never used as authority on their own.
- Current same-user authority is required for replay through another connection.
  The original preparation grant remains the dispatch authority. Missing original
  authority, a removed plan/draft, altered content, lost current recipient access
  or an unavailable frozen registration prevents a new provider handoff.
- No cancellation, removal, unpublish or draft replacement tool is exposed.

## Native worker and preservation

The native worker retains its existing durable-attempt commit before provider I/O.
MCP then acquires control/shared, original grant/update, identity/shared, plan/update,
agency/shared, ordered groups/access/shared, frozen device sessions/shared,
registrations/update, notification parents/update and delivery rows/update. A final
read-only grant/MFA clock check occurs immediately before provider handoff after
lock waits. Locks remain through result persistence and caller commit.

A wave contains ordinary work or one MCP origin, never both. Registration update
locks avoid shared-to-update upgrade cycles; separate waves avoid an ordinary
parent-to-registration writer cycling against the MCP registration-to-parent
barrier. The selection's earlier parent locks are released by the durable claim
commit before MCP authority locks are requested.

The existing native implementations submit at most twenty targets concurrently,
with a configured per-target timeout of 1–30 seconds (default 10). FCM credentials
are prepared before the source-lock transaction. The existing PostgreSQL transaction
allowance is 60 seconds during provider handoff. Unknown external outcomes are not
automatically resent. Stale durable attempts become unknown through existing recovery.

Denied origins fail only definitely-unsent retry targets. Existing accepted,
delivered, receipt-pending and unknown attempts remain retained. Provider acceptance
does not become delivery. Mutable operation observations use `SKIP LOCKED` to avoid
operation/plan lock inversion; explicit inspection deterministically catches up even
after terminal dispatch, without rewriting the initial queue receipt.

## Executed evidence

- 94/94 combined tests passed in 42.03 seconds: the two new integration modules
  (`test_mcp_gc_push.py`, `test_mcp_gc_push_drafts.py`) and existing authored
  notification, native FCM dispatch, mobile notification, saved-draft deletion and
  website route regressions. New cases include full SDK text → draft → preview →
  confirm, APNs environment routing, exact audience/content/device drift, bounds,
  immutable cross-connection replay, final grant expiry and partial accepted/unknown
  preservation after original authority is revoked.
- 11/11 real PostgreSQL tests passed in 33.31 seconds in
  `tests/service_integration/test_mcp_gc_push_postgresql.py`. They cover concurrent
  append-only draft creation and confirmation, rollback, live handoff versus grant,
  emergency control, role and security-version changes, separate ordinary and
  distinct-grant MCP waves, crash recovery without resending, and terminal
  observation catch-up after a held operation lock.
- PostgreSQL tests use guarded loopback CI storage and retain newly created UUID
  schemas. They do not delete or change existing public-schema records. Every
  provider is synthetic. Migration 0122 and retention proof are owned by the root
  integration checkpoint, separately from ORM/locking tests.
- Mypy passed eleven implementation sources; focused Ruff passed; the existing
  backend quality budget check passed all 87 tracked modules.

## Remaining scope

These tools cover authored native push, not a general-purpose email provider.
The existing email provider interface is inbound-only, Gmail uses a read-only scope,
and AI email action policy blocks sending. Recovery SMTP is not repurposed.
Ordinary GC announcement creation/version changes and publication are separate
workflows under review. This checkpoint does not mark the entire communications
phase or the complete MCP rollout as finished.
