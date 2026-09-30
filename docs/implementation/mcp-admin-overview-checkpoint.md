# Administrative overview read checkpoint

This finite Phase 3 slice exposes `get_admin_overview()` with no arguments. It
shares the website's seven count queries through `AdminOverviewRepository` and
the neutral `AdminOverviewCounts` shape. The existing HTTP response and role
dependency remain unchanged. This is a recorded-business-data observation, not
host configuration, service health, account details or complete administration.
The ledger stays `implemented_unverified` pending combined regression and
deployed acceptance.

| Field | Preserved website predicate |
| --- | --- |
| `agencies` | All authorized agencies, including inactive agencies |
| `users` | All authorized users, including inactive and retained deleted users |
| `client_groups` | All authorized groups, including closed, archived and deleted groups |
| `passport_submissions` | Office-visible passport statuses under every parent group status |
| `pending_review` | Pending-review passport statuses whose parent is neither archived nor deleted |
| `client_submitted` | Office-visible passport statuses whose parent is neither archived nor deleted |
| `failed` | Failed passport status whose parent is neither archived nor deleted |

The existing domain constants define the office-visible and pending-review
status families. No new distinct-person interpretation, active-agency predicate,
soft-deletion predicate, import-only exclusion or expired-trip exclusion is
introduced. Superadmin website observations remain global, including actors
without an agency. Agency-admin website observations retain exact agency
predicates, including SQL `IS NULL` where the actor lacks an agency; the agency
count itself uses the agency primary key and therefore returns zero in that case.
The website continues to reject roles outside Superadmin and Agency Admin.

MCP requires fresh, locked enabled-control, grant and active Superadmin identity
checks plus enabled `mcp:read` capability and principal/grant user binding. This
does not enable agency-admin access to MCP. Because the authorized Superadmin's
overview is global, the service performs no extra actor lookup after the mandatory
authority path. No caller-supplied actor, agency, role or scope is accepted.

The service deadline is ten seconds for authority and all seven source queries
combined. Source queries each return one scalar count and hydrate no business
models, large passport JSON, account credentials, group text, configuration or
file locators. Existing mandatory authority checks still read and lock the grant
and current identity/security records; they are separate from the seven business
projections. The service performs three authority queries plus seven counts;
transport token checks and content-free invocation auditing are additional.
Aggregate database scans are time-bounded, not artificially limited to the export
source-row ceiling. This does not prove a production memory or scan-time budget.

The whole structured response is bounded to 8 KiB using escaped ASCII JSON,
including actual environment/revision and a conservative fixed-width reserve
for the invocation timestamp and audit UUID. Every count must be a nonnegative
signed-64-bit integer and all seven fields must be present, with no extras.
Results explicitly describe `platform_global`, complete fixed-field coverage and
`live_multi_query` consistency with `snapshot_guaranteed: false`. Counts can
change between queries and are not an atomic snapshot or unique-person count.
Busy, oversized and unexpected failures return no partial counts and use fixed
safe messages. Cancellation propagates and requires ordinary caller rollback
before reuse of a cancelled database session.

The tool does not change accounts, settings, grants, groups, passports, exports or
operation receipts. It performs no storage/provider calls, file acquisition,
queue work, message sending, recovery, removal or security-control changes.
Normal token-use bookkeeping and content-free MCP invocation audit records
remain the only transport writes.

## Exact finite ledger change

The three existing surface rows are:

1. `route:backend/app/presentation/api/v1/routes/admin.py:get_admin_overview:GET:/overview`
2. `openapi:GET:/api/v1/admin/overview`
3. `frontend:frontend/features/operations/api/operations.api.ts:adminOverview`

Only their implementation records change, plus one new MCP tool row. The
frontend callable's prior Phase 7 classification is explicitly corrected to
Phase 3, matching the existing source and OpenAPI read classification. Existing
dispositions, requirements, effect-review fields, unrelated rows and contract
fingerprints remain unchanged. There is no frontend or OpenAPI schema edit.

## Component evidence and remaining gates

- Fourteen service/SQL cases pass in 4.91 seconds. The synthetic fixture has
  112 passports across two agencies, all four group statuses and all fourteen
  passport states. It demonstrates canonical fixed expected counts rather than
  deriving expected values from the shared implementation. Cases cover global
  and agency/NULL scope, inactive and retained records, seven scalar queries
  without private-column hydration, empty source tables, response/count bounds,
  authority/source deadlines and foreign principal rejection.
- HTTP/SDK tests and existing administrative website regressions initially pass
  **49 cases in 19.38 seconds**, retained in
  `outputs/mcp-admin-overview-http-web.xml` (15 new cases and 34 existing website
  cases). After adding the real SDK client case, all **16 new HTTP cases pass in
  18.63 seconds**, retained in `outputs/mcp-admin-overview-sdk-http.xml`.
  They cover fixed tool schema, HTTP role parity, safe successful audit, eight
  current-authority denial variants and static timeout/size/unexpected failures
  with no partial counts and a clean retry.
  OAuth issuance is real application logic against synthetic local data, followed
  by the installed SDK client and server over an in-process HTTP transport. This
  is not a deployed Codex or real network/provider test.
- Independent PostgreSQL component tests: **17 passed in 5.97 seconds**,
  retaining `manual_review_a46c84c5b1c44205be7bbe6e7689a239` and the receipt
  `outputs/mcp-admin-overview-postgresql.xml`. These prove exact canonical global,
  agency-admin and NULL-agency scope, legacy parent-status versus deletion-timestamp
  semantics, seven scalar plus three authority SQL queries, exclusion of 2 MiB
  opaque source values, no business ORM hydration, full response Unicode bounds,
  nine current-authority denials, actual blocked source/grant deadlines, identity
  serialization, external cancellation and clean rollback/retry. Full business-row
  hashes and operation/artifact/history/message/audit counts are unchanged by the
  direct service. No public or production rows are mutated and no schema/data is
  removed. Tables are ORM-created in a uniquely retained loopback schema; this is
  not migration, restricted-runtime-role or combined-capacity qualification.
- Strict mypy passes for four new production modules; scoped Ruff, all 87 quality
  budgets and the two exact root-reviewed infrastructure edges pass.
- Inventory classification passes for 1,508 surfaces and 83 tools; all twelve
  inventory tests pass. A parsed finite-row comparison verifies only three
  implementation objects, the approved frontend Phase 7 to 3 correction and one
  new tool changed, preserving every unrelated ledger entry.

Combined full regression, deployed actual Codex invocation and same-host capacity
qualification remain separate pending gates. This checkpoint does not activate
production capabilities or alter production configuration.
