# Dashboard summary read checkpoint

Locally qualified on 2026-09-30. `get_dashboard_summary` implements the finite
[dashboard read contract](mcp-dashboard-read-contract-checkpoint.md). Its three
existing frontend/source/OpenAPI ledger representations and its new tool entry
are `implemented_unverified`, Phase 3. This does not complete the read phase,
other dashboard/analytics workflows, deployment or live Codex qualification.

The tool takes no agency, user, filter or pagination arguments. The audited MCP
boundary requires the current `mcp:read` grant and active Superadmin identity;
the service rechecks the actor and uses that actor's current agency. No agency
returns four zero counts and an empty preview, matching the website rather than
aggregating other agencies. No impersonation or alternative agency is available.

The website and MCP now share the bounded recent-submission repository method
through the existing dashboard use case. The existing agency, parent visibility,
status-family, staff ownership/assignment and lifecycle clauses were extracted
unchanged into one scope helper for lists, counts and the preview. The HTTP
response schema is unchanged. Total passport submissions retains its canonical
role-specific archive/deletion visibility; pending, confirmed and recent values
retain their additional archived/deleted-group status exclusion. `active_links`
still counts active visible groups, including a group whose trip is past; it is
not a claim that an upload credential is usable. These are passport submission
counts, not operational passenger or WhatsApp audience counts.

The preview selects only ID, client name, client email, status, creation time and
overall confidence. It returns at most five rows ordered by `created_at DESC,
id DESC`. SQL bounds names and emails to 256 characters before materialization;
an extra character detects a value exceeding the canonical 255-character column
bound and produces an explicit unavailable result, never a silently truncated
preview. Passport JSON, document keys and full passport/group ORM objects are
not materialized. Aggregate counts remain database-side and are not capped by
the deployment's export row limit.

The complete service read has a 10-second application deadline. A normal
observation makes seven SQL statements: two current identity reads, four counts
and one preview. The no-agency path makes only the two identity reads. The
service payload is limited to 32 KiB of ASCII-escaped JSON before the common
audit/environment envelope; non-finite confidence values are rejected. Existing
transport, authorization and audit database limits remain separate. Counts and
rows come from separate live queries, explicitly without an atomic snapshot or
a freshness guarantee derived from frontend polling.

Authorized client names and email addresses remain part of the website-equivalent
preview and are marked as untrusted business data. Errors are static and never
return partial counts, source values, SQL or exception text. The only MCP effect
is its invocation audit; there is no business write, operation/idempotency key,
artifact, export history, render, background job or message dispatch.

## Evidence

- [Dashboard SQL/SDK HTTP tests](../../backend/tests/integration/test_mcp_dashboard_summary.py)
  plus the existing [use-case test](../../backend/tests/unit/application/test_dashboard_use_cases.py):
  **18 passed**. Independent expected count assertions and actual website/MCP
  equality cover mixed agencies, six office-visible status families, excluded
  draft/error states, staff assigned/owned scope, role-specific retained groups,
  tied timestamps, six recent candidates yielding five, no-agency zero behavior,
  live authority changes, SQL projection shape, static bounds and timeout audit.
- Existing [authorization](../../backend/tests/unit/application/test_authorization_policy.py)
  and [retained-data policy](../../backend/tests/unit/application/test_retained_data_authorization.py)
  regressions: **48 passed**.
- [PostgreSQL qualification](../../backend/tests/service_integration/test_mcp_dashboard_summary_postgresql.py):
  **5 passed** against the dedicated loopback PostgreSQL 16.15 instance. A new
  UUID-owned schema and its synthetic records were retained. The cases prove
  174 visible submissions are counted despite an export ceiling of 100,
  12 MiB of unrelated retained JSON is excluded from the six-column preview,
  exact website parity and UUID tie ordering, identity-only no-agency behavior,
  complete 255-character Unicode fields, non-finite confidence rejection, and
  actual blocked-query cancellation followed by rollback and a successful retry.
  No public-schema business/control records were modified. This uses isolated
  ORM-created tables, not migration or restricted-runtime-role qualification.
- Strict mypy on seven changed production modules, scoped Ruff, all 87 backend
  quality budgets and whitespace checks passed. The four new repository import
  edges are explicitly reviewed in the architecture policy.
- Inventory check passed with 1,494 surfaces and 69 tools in this isolated
  checkout; all 12 drift tests passed. An exact parsed comparison confirmed
  only the three dashboard implementation objects and one new tool row changed.
  Existing requirements, classifications, fingerprints and all other rows were
  retained. Other isolated branches may add their own tools during integration.

These **71 tests** are distinct focused cases, not a full backend aggregate.
The PostgreSQL lane retains its schema identifier in the JUnit receipt
`outputs/mcp-dashboard-postgresql.xml`. Commands were run with the shared Python
3.11 environment and the dashboard checkout's `backend` as the explicit working
directory; the imported `app` path was checked before execution.

The dashboard was subsequently integrated with Excel option discovery at
`27afeb4ce0bb427eb4a87eb0913f92f36f2b3e59`. The combined focused run passed
56 cases; inventory checking reported 1,495 surfaces and 70 tools, with the
architecture contract and all 87 budgets passing. The full combined regression
then passed **5,921 tests, three skips, 318 deselected and 162 subtests** in
998.28 seconds, exit zero. The skip and separate service-integration boundaries
remain explicit. The qualified revision was pushed directly to `main` with
hosted CI skipped.

The reviewed backend-only deployment subsequently succeeded. Two actual Codex
calls against `27afeb4c` passed deterministic tool-event and schema validation;
the resulting four current-user counts and five-row preview size matched the
authenticated website at an adjacent observation. The
[release checkpoint](mcp-options-dashboard-release-checkpoint.md) records exact
bindings, runtime/audit evidence and safe receipts. Other role/data variants,
combined Linux/VPS resource qualification and the complete phase remain open.
