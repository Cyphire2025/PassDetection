# Office attendance summary and missing-passenger read checkpoint

Local implementation checkpoint, 2026-09-30. `get_group_attendance_summary` and
`list_missing_attendance_passengers` provide the canonical office summary and
missing-passenger family through `mcp:read`. Exactly six existing source, OpenAPI
and frontend rows plus two tools are `implemented_unverified`, Phase 3. The
combined backend aggregate after integration, deployment, actual Codex readback
and combined capacity qualification remain pending for this slice. The remaining
attendance workflows and all eight goal phases remain open.

The [MCP service](../../backend/app/application/mcp/attendance_reads.py) requires
a current active Superadmin grant with `mcp:read`, then uses only the connected
account's current agency. There is no agency argument or impersonation override.
The exact group must belong to that agency and have status other than `deleted`;
the existing `AuthorizationPolicy.require_assign_coordinator` applies. This
preserves the website's retained `deleted_at` semantics rather than introducing
a new exclusion. The account/grant and group checks occur within the five-second
service deadline and shared transaction. Website roles remain unchanged and do
not acquire MCP connection eligibility. Missing or out-of-scope groups return a
fixed unavailable error.

The [shared service](../../backend/app/application/use_cases/attendance_dashboard.py)
retains canonical activity aliases, approved operational roster predicates,
first-scan coordinator attribution and closeout checkpoint classification. A new
[pure projector](../../backend/app/application/use_cases/attendance_projection.py)
serves both the website and MCP; the website response shapes and default query
limits are unchanged. Qualification found and fixed one inherited website bug:
an activity with neither roster rows nor scans called `max` with a single datetime
argument and raised `TypeError`. The helper now takes the maximum of a nonempty
datetime sequence, so this valid empty state returns the activity's own timestamp,
zero counts and an empty missing page. No synthetic passengers or scan evidence
are created to satisfy the query.

`get_group_attendance_summary(group_id)` returns the complete canonical activity
list within the admitted scope, live attendance counts and reported queue
readiness. It preserves the website's deterministic projection of at most 25
coordinators, together with `coordinator_count` and `coordinators_truncated`; MCP
marks the response `partial` when this cap is used. Empty groups return a complete
empty activity list. An activity with no participants has no affirmative closeout
readiness evidence. Runtime/checkpoint metadata is not proof of physical presence
or permission to close an activity.

The response and tool descriptions state the canonical count semantics explicitly:

- `present_count` counts distinct retained passenger IDs across the canonical
  activity and its aliases, including IDs removed from the current approved roster.
- `missing_count` is `max(current approved roster count - retained present count, 0)`.
- Missing-passenger pages apply current approved roster membership and exclude
  members with a retained family record. Their row count can therefore differ from
  the summary's `missing_count` after roster changes. Neither is a physical-presence
  assertion. A regression removes a scanned passenger through an active rejected
  roster resolution while retaining all three scans: the summary remains present
  2, becomes missing 3, and the missing page still contains 4 current members.

`list_missing_attendance_passengers(group_id, session_id, snapshot_revision,
page_size=50, cursor=null, search=null)` returns only current missing passenger
UUIDs and names, ordered by UUID ascending. The page size is 1 to 100. Search is
normalized and bounded to 120 characters with literal SQL wildcard escaping.
The revision input is the selected summary session's nested `revision`, not the
summary's top-level `snapshot_revision`. Top-level `revision` is always deployed
code identity from the common invocation envelope.

Thirty-minute signed cursors bind actor, current agency, group, canonical session,
activity revision, normalized search and page size. They cannot be moved to a
different authorized account or query. The shared before/after canonical aggregate
revision fence rejects observed scan/roster changes and requires a fresh summary.
Summary queries are live and neither endpoint promises an atomic or immutable
snapshot. The aggregate revision is the existing website fence, not an exhaustive
change log; compensating or backdated changes that leave its aggregate inputs
unchanged are not claimed to be detected. The cursor's timestamp belongs to its
expiry state and does not create a historical database snapshot.

MCP-only admission bounds the actual materialization queries, not a separate
earlier count vulnerable to concurrent insertion. The repository reads at most
101 canonical activities to admit 100, and at most 5,001 rows to admit 5,000 for
each assignment, checkpoint, runtime and participant source. Before Python
classification, it also requires
`activity_count * (assignment_rows + checkpoint_rows + participant_rows) <= 10,000`.
This conservative derived-work bound avoids expanding 100 activities across
5,000 assignments. Exceeded bounds return a static limit error, never a silently
truncated source projection. These limits describe supported requests, not a
general workload or production capacity qualification.

The opt-in repository projections select scalar columns only. They exclude
private runtime identifier hashes, native session IDs, device IDs, client event
secrets, passport JSON, email, phone and storage locators. Group, coordinator and
passenger names use a database-side 256-character sentinel; activity names use
161, detecting the canonical 255/160 limits without returning clipped content.
Missing rows use page-size-plus-one admission. Names remain authorized untrusted
business text. The complete ASCII-escaped structured response, including the
common environment, revision, timestamp and audit ID, must fit within 512 KiB.
Fresh authority, scope, queries and projection share the five-second application
deadline; existing transport/token verification/audit bounds remain separate.

Cancellation and lock timeout leave transaction rollback to the shared invocation
or caller. Fixed errors distinguish invalid cursor/input, unavailable group or
activity, changed revision, busy reads and exceeded limits without exposing SQL
or raw source contents. There are no scan, checkpoint, close, acknowledgement,
device impersonation, operation/idempotency, export, storage or provider actions.
Only the shared MCP invocation audit is added. Legacy full attendance overview,
mobile/coordinator reads, device queues, closeout mutations and other planned
attendance surfaces are not promoted by this slice.

## Local evidence

- [MCP SQL/HTTP/SDK tests](../../backend/tests/integration/test_mcp_attendance_reads.py),
  canonical website/shared repository tests and four architecture regression
  tests pass together: **111 passed in 40.89 seconds** on the final source. This
  includes 31 new integration cases and the new shared empty-activity unit case;
  the earlier 105-test and 31-test checkpoints overlap this final run and must not
  be added to it. Actual SDK checks cover own-agency schemas, current authority,
  website equality, aliases, signed pagination, literal search, invalid inputs,
  observed revision changes, the 26-coordinator partial response, distinct group
  versus activity revisions, private-column/ORM exclusion, no business writes,
  text sentinels, response budget and static deadline errors.
- [Independent PostgreSQL tests](../../backend/tests/service_integration/test_mcp_attendance_reads_postgresql.py):
  **28 passed in 9.88 seconds** on final source using loopback PostgreSQL 16.15
  and retained schema `manual_review_0014c0809edc4c3db0e8a151b68d3af4`. They prove
  actual 100/101 activity and 5,000/5,001 assignment boundaries, derived admission,
  large Unicode response rejection, scalar runtime/checkpoint projections,
  website/alias/missing parity, retained-scan/current-roster divergence, current
  scope and cursor bindings, committed mid-query scan conflicts, lock timeout and
  external cancellation followed by rollback and a clean retry. The initial
  27-case run had three failures exposing the shared empty-activity bug; that
  receipt is retained, and the corrected run adds an explicit empty-state case.
  No public business/control records were changed or cleaned up. These are
  isolated ORM-created tables, not migration, runtime-role or load qualification.
- Strict mypy passes for ten affected production modules; scoped Ruff, all 87
  backend quality budgets and the architecture validator pass. Eight exact
  infrastructure imports were reviewed and recorded; no rule or budget was
  relaxed. The complete generated OpenAPI contract matches its existing snapshot.
- Inventory passes with **1,503 surfaces / 78 tools** in this isolated checkout;
  all **12 drift tests pass**. Parsed comparison confines changes to requirements
  and implementation evidence on the six approved existing rows plus two new
  tools. Existing dispositions, phases, fingerprints, all other rows and top-level
  ledger metadata remain unchanged. Read contracts replace the two frontend rows'
  generic mutation requirements; they do not classify the business workflows out
  of scope.

Ignored receipts are `outputs/mcp-attendance-focused-final.xml`,
`outputs/mcp-attendance-final-integration.xml`,
`outputs/mcp-attendance-reads-postgresql.xml` and
`outputs/mcp-attendance-reads-postgresql-2.xml`. Root integration owns the combined
full regression and any deployment/readback; none is asserted by this checkpoint.
