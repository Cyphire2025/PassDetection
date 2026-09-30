# Explicit group passport-retention observation

This finite Phase 3 slice adds `get_group_passport_retention(group_id)` under
`mcp:read`. It observes the stored schedule for one explicit group through the
same scalar repository and neutral projection as the existing website GET. The
ledger remains `implemented_unverified`; local component qualification does not
complete the phase, establish deployed acceptance or qualify retention execution.

The website still returns exactly `group_id`, `passport_purge_at` and
`passport_retention_days_applied`, with its existing role dependency and missing
group HTTP404. Superadmins retain access to any exact group, including cross-agency,
archived and deleted groups, inactive agencies and actors without an agency.
Agency administrators retain only their matching agency, including the existing
SQL NULL-agency semantics. No active, deleted, status or legal-hold filter is
introduced. Retired legal-hold controls remain unavailable for mutation.

The shared repository selects four scalar columns: group ID, agency ID, stored
purge timestamp and applied retention days. It does not hydrate private group
fields, passport submissions, files or a retention job. The MCP result adds the
group's agency ID, explicit-group scope, complete-result metadata and a fixed
notice. Nullable timestamps and nullable applied days are preserved; valid days
follow the existing database range of 1 through 3,650. MCP serializes timestamps
as UTC instants. The website response schema and native timestamp projection are
unchanged. One legacy SQLite assertion now compares UTC instants explicitly,
because a fresh scalar load loses the timezone marker that a cached ORM value
retained; its three-field response assertion remains intact.

MCP requires fresh active Superadmin identity, the current grant and `mcp:read`.
Control, grant and identity locks precede a SHARE lock on the explicit group. The
five-second whole-read deadline includes authority and source waits. The result
has an 8 KiB bound over the complete escaped structured response, including actual
environment/revision and fixed-width audit/observation metadata. Missing scope,
expired authority, busy reads and exceeded limits return static failures without
a partial schedule. SQL scalar count is three authority statements plus one
business statement; normal transport token validation and auditing are additional.

A saved date, a past date or a null value does not prove that a purge happened,
identify remaining records or files, or authorize scheduling, cancellation or
deletion. This tool does not inspect storage, run cleanup, dispatch a job, contact
a provider, change settings or alter retained data. The ordinary content-free MCP
invocation audit and token-use bookkeeping are the only transport writes.

## Exact ledger scope

These two existing Phase 3 rows change only their implementation evidence:

- `openapi:GET:/api/v1/admin/groups/{group_id}/passport-retention`
- `route:backend/app/presentation/api/v1/routes/admin.py:get_group_passport_retention:GET:/groups/{group_id}/passport-retention`

The newly discovered tool row is
`mcp_tool:backend/app/presentation/mcp/retention_read_tools.py:get_group_passport_retention`.
All three remain `implemented_unverified`. There is no corresponding callable
frontend surface in the inventory, so none is invented. Existing dispositions,
phases, requirements and declaration fingerprints are preserved; no unrelated
workflow is reclassified or marked complete.

## Local evidence and remaining gates

- New service, real OAuth/MCP HTTP, website HTTP and existing platform-retention
  controls: **35 passed in 28.24 seconds**. Coverage includes exact three-field
  website parity, retained/cross-agency and NULL-agency semantics, four scalar
  columns without private ORM hydration, schema/role/capability denials, safe
  audits and static timeout/size/unexpected failures with retry. Initial failures
  were two invalid synthetic role strings and the SQLite timestamp assertion
  described above; their receipt is retained separately.
- Independent PostgreSQL tests: **27 passed in 5.62 seconds**, retained schema
  `manual_review_abf5b5c0fc1a48a0ac90597b438778e0`. They prove six canonical
  null/past/future/held/retained/inactive schedule variants, Superadmin global
  access including no-agency actors, website own/NULL-agency behavior, twelve
  current-authority denials, whole-envelope Unicode admission, real group/grant/user
  lock deadlines with rollback and retry, source SHARE-lock writer exclusion,
  external cancellation and committed revocation winning before a waiting read
  reaches the business query. Private group/passport columns are never hydrated;
  complete business row hashes and effect counts remain unchanged. The initial
  run had one invalid disabled-MFA fixture; its corrected rerun changes no
  application source. This is an ORM-created isolated loopback schema, not
  migration, restricted-role, production-memory or combined-load qualification.
- Six production modules pass strict mypy. Scoped Ruff, architecture validation
  with the two explicitly reviewed repository imports, and all 87 backend quality
  budgets pass. All four architecture regression tests pass. Inventory covers
  1,508 surfaces and 83 tools; all 12 drift tests pass. A parsed comparison confirms
  only the two approved implementation objects and one new tool row changed.

Ignored receipts are `outputs/mcp-retention-focused-initial.xml`,
`outputs/mcp-retention-focused-final.xml` and
`outputs/mcp-retention-reads-postgresql-final.xml`. Tests use the existing Python
3.11 environment with this isolated checkout's backend as the working directory.
No production services, grants, schema or records were changed. Combined source
regression and actual deployed Codex acceptance remain separate pending gates.
