# Personal notification read and acknowledgement checkpoint

Locally qualified on 2026-09-30. This finite slice implements two tools and six
existing website surface representations. The ledger remains
`implemented_unverified`: local component evidence is not deployed acceptance,
completion of Phases 3/7, or combined production capacity qualification.

`list_my_notifications` requires current `mcp:read` authority and an active
Superadmin. It has no user or agency override. The website and MCP share the
mandatory personal `user_id` predicate, optional canonical agency filter,
priority/unread filters, stable ordering and unread-count query. The canonical
Superadmin scope crosses agencies only for notifications personally targeted
to that account, including a Superadmin with no agency. Other recipients and
legacy agency-wide rows (`user_id IS NULL`) are excluded. The agency-wide legacy
list, bulk mark-read and all notification generation/dispatch actions remain
outside this slice.

The read uses a signed, actor/filter/page-bound creation-cutoff cursor, at most
100 returned rows plus one lookahead, and `created_at DESC, id DESC`. The unread
count covers the whole personal unread feed independently of page/priority,
matching the website. Separate live queries do not guarantee an atomic snapshot;
mutable read flags and counts may change between pages. The normal service read
uses four SQL statements (two identity, one scalar page, one count), a 10-second
application deadline and a 256 KiB UTF-8 JSON service payload bound before the
common audit/environment envelope. Current authorization and audit database
work remains subject to its own transport/database limits.

The scalar page bounds all text in SQL before materialization: type 80, title
255, message 4,096, entity type 80, entity ID 128, priority 16 and category 40
characters. One sentinel character detects overflow; overbounds fail the whole
page explicitly, including lookahead, rather than silently truncating content.
Arbitrary metadata and full Notification ORM objects are never hydrated. Only
typed string metadata `provider` (32), `account_email` (320) and `group_name`
(255) is returned; all other metadata is explicitly omitted. Known keys with
non-string values are omitted, and known oversized strings fail. Authorized
notification text and these metadata fields are untrusted business content,
never instructions or authorization to perform another action.

`acknowledge_my_notification` requires current `mcp:change` authority and an
explicitly selected personal notification ID. The only business mutation is a
single false-to-true `is_read` transition. It preserves any existing `read_at`,
otherwise records the first acknowledgement time. Existing content, metadata,
ownership and all other notifications remain unchanged. An already-read row is
a no-op, even when its historical timestamp is absent. This acknowledgement does
not resolve an underlying alert, send or retry a message, create a notification,
schedule work, invoke a provider, or delete anything.

The existing durable operation transaction takes current control/grant/identity
authority, then the operation record, then the personally owned notification
with `FOR UPDATE NOWAIT`. A fixed `notification_busy` error leaves no poisoned
operation or read mutation; retry uses the same ID and key. The first-read
change and a content-free business audit are atomic. Response-loss recovery on
the same or a newly authorized connection for the same actor returns the saved
immutable receipt, after current authority and saved recipient/agency/read-state
checks. It never reapplies a past read mutation. A new key for an already-read
notification records a no-op receipt without changing the timestamp. Missing,
foreign and shared notifications return one static unavailable error. Only the
selected ID is accepted in the mutation payload; scope cannot be widened.

## Exact six existing surface rows

1. `frontend:frontend/features/notifications/api/notifications.api.ts:feed`
2. `frontend:frontend/features/notifications/api/notifications.api.ts:markRead`
3. `openapi:GET:/api/v1/notifications/feed`
4. `openapi:POST:/api/v1/notifications/{notification_id}/read`
5. `route:backend/app/presentation/api/v1/routes/notifications.py:notification_feed:GET:/feed`
6. `route:backend/app/presentation/api/v1/routes/notifications.py:mark_notification_read:POST:/{notification_id}/read`

Only those six implementation objects and the two new MCP tool entries change
in the coverage matrix. Existing phase assignments, requirements, classifications
and unrelated fingerprints are retained. The adapter is
`backend/app/presentation/mcp/notification_tools.py`. Website response schemas,
authorization behavior and its existing mark-read implementation remain intact;
the MCP acknowledgement deliberately adds durable, monotonic first-read semantics.

## Retained evidence

- New SQL/service tests
  [reads](../../backend/tests/integration/test_mcp_notification_reads.py),
  [acknowledgements](../../backend/tests/integration/test_mcp_notification_changes.py)
  and [OAuth/SDK HTTP](../../backend/tests/integration/test_mcp_notification_http.py),
  plus the unchanged canonical
  [website feed regressions](../../backend/tests/unit/infrastructure/test_notification_feed.py):
  **50 passed in 29.38 seconds**. Evidence covers web equality, no-agency personal
  scope, foreign/shared exclusion, tied UUID pagination, cursor binding,
  2 MiB unknown-JSON exclusion, field and Unicode byte bounds, first timestamp,
  immutable same-key/cross-grant replay, new-key no-op, audit-failure rollback,
  conflict rejection and eight live authority-denial variants. HTTP failures are
  fixed, audited and do not return partial pages or sensitive sentinels.
- [PostgreSQL component tests](../../backend/tests/service_integration/test_mcp_notifications_postgresql.py):
  **6 passed in 3.36 seconds** on the dedicated loopback PostgreSQL instance.
  A retained schema `manual_review_541876c9da704dd189a8f5642ebc2f15` holds synthetic
  data only. It proves 153 personal rows across two agencies, a 101-row bounded
  scalar fetch excluding a 2 MiB arbitrary metadata value, exact website IDs and
  count, Unicode output limits, six concurrent same-key calls across two grants,
  first-timestamp preservation, actual NOWAIT mutation and replay contention,
  and blocked SQL cancellation followed by rollback and successful retry.
  No public business/control records, provider, storage or network delivery was
  involved. Tables are ORM-created in the private schema; this is not migration,
  restricted-runtime-role or production load qualification.
- Seven-module strict mypy, scoped Ruff and all 87 backend quality budgets
  pass. The architecture policy explicitly reviews eight change-service and
  three read-service infrastructure import edges. Independent source review
  found no ownership or side-effect blocker.
- Inventory classification passes with 1,497 surfaces and 72 tools in this
  isolated checkout; all 12 inventory drift tests pass. A parsed comparison
  proves only the six implementation objects and two new tool entries changed.

Ignored JUnit receipts are `outputs/mcp-notifications-focused.xml` and
`outputs/mcp-notifications-postgresql.xml`. Tests use the existing Python 3.11
runtime with this isolated checkout's backend as their explicit working directory.

Full aggregate regression and integration remain required at this checkpoint.
The production deployment profile remains read/export only; this work does not
enable `mcp:change`, widen grants, modify schema/control settings or deploy code.
Real deployed Codex invocation and same-host combined-load gates remain open.
