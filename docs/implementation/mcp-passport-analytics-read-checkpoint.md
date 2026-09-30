# Canonical passport analytics read checkpoint

Local implementation checkpoint, 2026-09-30. `get_passport_analytics_summary(days=30)`
provides the existing passport analytics summary through `mcp:read`. Three existing
frontend, source and OpenAPI rows plus one tool are `implemented_unverified`.
The frontend `operations.analyticsSummary` row is corrected from Phase 7 to
Phase 3 because its source only calls the same read-only GET summary. Its generic
mutation requirements are replaced by the canonical read contract. The two HTTP
rows stay in Phase 3. All other classifications, metadata and fingerprints remain
unchanged. Combined full regression after integration, deployment, actual Codex
readback and combined capacity qualification remain pending for this slice.

The [shared use case](../../backend/app/application/use_cases/passports/passport_analytics.py)
and [scalar repository](../../backend/app/infrastructure/repositories/passport_analytics_repository.py)
extract the website's existing behavior. The website route retains its roles,
signature, default day count, response shape and status code; the complete OpenAPI
snapshot is unchanged. The shared four-field projection contains status counts,
confidence buckets, submissions by day and average confidence.

The [MCP service](../../backend/app/application/mcp/analytics_reads.py) revalidates
the current locked grant/account and `mcp:read` capability inside its five-second
deadline. It reads the fresh actor and uses the canonical Superadmin scope:
**all agencies, including a Superadmin account without an agency**. There is no
caller agency parameter. The website's non-Superadmin own-agency filter remains;
an agency administrator without an agency receives the same empty dictionaries
and null average as before. Staff or agency-admin website access does not create
MCP connection eligibility. No active-agency, group-status, soft-deletion or
operational-roster filter is added to this canonical analytics workflow.

Integer `days` defaults to 30 and clamps to 1 through 365. The cutoff remains
`created_at >= now - days`, using a UTC lower bound and **no upper bound**.
Future-dated records therefore remain eligible, even far beyond the nominal
window. The service exposes the effective day count, `window_start` and a null
`window_end`; it does not silently turn this into a closed date interval.

All three queries use exactly `OFFICE_VISIBLE_PASSPORT_STATUS_VALUES`:
`client_submitted`, `confirmed`, `submitted`, `ai_approved`, `needs_review` and
`staff_approved`. Each status result counts rows. The confidence query retains
the exact canonical SQL comparisons:

- High: confidence at least `0.9`.
- Medium: between `0.75` and `0.899`, inclusive.
- Low: confidence below `0.75`.
- Missing: SQL `NULL`.

Values strictly between `0.899` and `0.9` appear in no confidence bucket but still
contribute to the average. Finite negative values and values above one retain
their existing comparison/average behavior; the adapter does not clamp them.
The average excludes SQL nulls and rounds the resulting float to three decimal
places. An empty global result has no status/date keys, four zero confidence
buckets and a null average. Bucket sums need not equal status totals even without
concurrent changes.

The day query retains `CAST(created_at AS DATE)` and ascending date order.
For PostgreSQL timestamps with timezone, that cast follows the **database session
timezone**, not an invented application UTC grouping rule. The MCP response states
this and does not claim to have observed the timezone's name. Status counts,
bucket counts/average and day counts are three separate live queries. The response
explicitly disclaims an atomic or historical snapshot, and no cross-query total
equality is imposed.

All business reads are scalar SQL aggregates. No passport ORM object, name,
email, source JSON, file locator or processing/provider data is materialized.
Status cardinality is fixed by the six-status filter; the bucket query returns
one row. The MCP day query uses **`LIMIT 367` on the actual grouped result**, admits
at most 366 groups and rejects an exceeded result without returning partial dates.
This catches numerous future-date groups; it does not rely on `days <= 365` as an
incorrect cardinality assumption. The website repository default remains unbounded.

MCP counts must be nonnegative integers no larger than signed 64-bit maximum,
and the rounded average must be finite when present. The complete ASCII-escaped
structured response, including common environment, revision, timestamp and audit
ID, is limited to **64 KiB**. Authority, scope, the three queries and projection
share a **five-second** service deadline; transport/token verification and audit
have their own existing bounds. Timeout/cancellation permits caller rollback and
a clean retry. Fixed public errors cover invalid input, exceeded bounds and busy
reads without raw database or source content.

The only MCP effect is the shared invocation audit. There are no operations,
idempotency keys, business writes/removals, files, exports/history changes,
provider calls or new event evidence. These bounded observations are not a
production workload qualification and do not implement other analytics families.

## Local evidence

- [Functional SQL/HTTP/SDK tests](../../backend/tests/integration/test_mcp_analytics_reads.py)
  plus four architecture regression tests: **32 passed in 37.92 seconds** on the
  final source. The suite includes 28 new analytics cases: website/MCP parity,
  all canonical statuses, the confidence gap, future records, day clamp, global
  Superadmin with/without agency, agency-admin scope, empty results, retained
  inactive-agency/deleted-group behavior, current authority denial, three scalar
  queries and no private columns/business writes, actual 367-day rejection,
  nonfinite/oversized aggregate denial, complete-envelope budget, SDK metadata
  and safe deadline/input rejection. The earlier 26-case passing run is a subset,
  not additional evidence. Initial fixture failures were missing required group
  IDs and were fixed in the test setup without application changes.
- SQLite does not implement PostgreSQL's timestamp-to-date cast. The local SQL
  fixture uses a test-only compiler shim rendering `date(timestamp)` for that
  expression; production SQL remains unchanged. PostgreSQL owns timezone and
  native cast qualification below.
- [Independent PostgreSQL tests](../../backend/tests/service_integration/test_mcp_analytics_reads_postgresql.py):
  **27 passed in 5.56 seconds** against final source using PostgreSQL 16.15 and
  retained schema `manual_review_5a5bc55094454e5084687743f12dc1aa`. The lane proves
  actual 366/367 date admission, the confidence gap and finite/nonfinite averages,
  scope/window/empty behavior, native UTC versus session-timezone casts, three
  scalar queries with ORM/private/provider exclusions, a Unicode common-envelope
  budget, nine current authority denials, database-lock and identity-lock deadlines,
  external cancellation, rollback and clean retries with unchanged business hashes.
  No public business/control records were changed or cleaned up. These are isolated
  ORM-created tables, not production, migration or restricted-runtime-role tests.
- Strict mypy passes on seven affected production modules. Scoped Ruff, all
  87 backend quality budgets, the architecture validator and unchanged OpenAPI
  check pass. Four exact infrastructure imports were reviewed and recorded;
  no validator or budget was weakened.
- Inventory passes at **1,508 surfaces / 83 tools**, and all **12 drift tests pass**.
  A parsed comparison confines ledger changes to the three approved requirements
  and implementation objects, the explicit frontend Phase 7-to-3 correction and
  one newly discovered tool. No other row or top-level metadata changes.

Ignored receipts include `outputs/mcp-analytics-focused-final.xml` and
`outputs/mcp-analytics-reads-postgresql-final.xml`. Root integration owns the full
combined aggregate and any deployment/readback. All eight goal phases remain open.
