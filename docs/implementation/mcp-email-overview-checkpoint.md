# Email readiness and personal summary checkpoint

This finite Phase 3 slice provides `get_email_integration_status()` and
`get_my_email_integration_summary()`, both without business-scope arguments.
It complements existing `list_email_records` pages: readiness flags and the
seven website counts cannot be reconstructed exactly from those retained record
projections. The ledger remains `implemented_unverified`; the
[later release checkpoint](mcp-read-observations-release-checkpoint.md) records
the integrated backend regression and selected deployed observations on
`1f4177cb`. This is not completion of email workflows, provider qualification or
combined production capacity.

The shared neutral readiness projector preserves the six website booleans:
`enabled`, `sync_enabled`, `attachment_processing_enabled`,
`auto_actions_enabled`, `ai_enabled` and `ai_notifications_enabled`. It returns
exactly Gmail and Outlook with code-owned labels and configuration-presence
booleans. Existing runtime readiness properties and nonblank secret-presence
semantics are reused. No credential value, client identifier, redirect URL,
encryption material or provider token enters the result. Configured does not
mean credentials were validated, a mailbox is connected, a provider is reachable,
workers are healthy or delivery succeeded. The projector never contacts providers.

The shared summary repository preserves exactly seven scalar website predicates:

| Field | Canonical recorded-data predicate |
| --- | --- |
| `connected_accounts` | Personal connections in active, failing or paused state |
| `relevant_emails_today` | Personal relevant messages received at or after UTC midnight |
| `documents_retrieved_today` | Personal artifacts with `retrieved_at` at or after UTC midnight |
| `automatically_matched_today` | Personal artifact-document links created at or after midnight, with the existing SQL `human_confirmed` boolean expression false |
| `revisions_detected_today` | Personal possible-revision reviews created at or after midnight, without an added status filter |
| `pending_review` | Personal reviews in open or deferred state, regardless of creation date |
| `retrieval_failures_today` | Personal failed artifacts with `last_error_at` at or after midnight |

Each query uses the canonical `email_owner_filters`. Superadmin observations span
only that actor's personally owned mailboxes across agencies, including when the
actor has no agency. Other recipients are always excluded. Existing website
agency restrictions for other permitted roles and its missing-agency HTTP403 are
preserved. This slice adds no active-agency rule, connection-state filter on other
count families, parent join, distinct-person interpretation, or upper time cutoff.
In particular, recorded future timestamps retain the website's `>= midnight`
behavior. The JSON predicate is evaluated by SQL; its evidence document is never
hydrated into application memory.

MCP requires a current active Superadmin, enabled `mcp:read` capability and fresh
control/grant/identity locks. No actor, agency, mailbox or effective-role override
is accepted. A ten-second application deadline includes current authority,
identity projection and the observation. The service uses four authority/identity
SQL statements plus zero business queries for readiness or seven scalar business
queries for summary. Common transport token authorization and invocation auditing
are additional. Large count scans are limited by time, not a claimed source-row
ceiling or measured production memory guarantee.

Results have an 8 KiB bound covering the complete structured response, including
actual environment/revision and fixed-width observation timestamp/audit UUID.
Summary counts are nonnegative signed-64-bit integers and include the UTC period
start, personal-owner scope and an explicit live-multi-query/non-atomic notice.
Separate queries may observe concurrent changes. Counts are stored records, not
unique people or proof of delivery. Readiness has a distinct configuration-only
notice. Returned text is fixed application metadata; no mailbox address, owner
ID, subject, body, filename, provider ID, raw error, match evidence or file locator
is projected.

The tools do not authorize accounts, connect, sync, pause, resume, retry, recover,
retrieve or generate files, process attachments, decide reviews, dispatch jobs,
send messages, change settings or remove records. The normal content-free MCP
invocation audit and token-use bookkeeping remain the only transport writes.
Visa AI status GET handlers remain outside this slice because their existing
website behavior can recover and dispatch generation work.

## Exact six existing surface rows

1. `frontend:frontend/features/email-integrations/api/email-integrations.api.ts:status`
2. `frontend:frontend/features/email-integrations/api/email-integrations.api.ts:summary`
3. `openapi:GET:/api/v1/email-integrations/status`
4. `openapi:GET:/api/v1/email-integrations/summary`
5. `route:backend/app/presentation/api/v1/routes/email_integration_connections.py:email_integration_status:GET:/status`
6. `route:backend/app/presentation/api/v1/routes/email_integration_activity.py:email_integration_summary:GET:/summary`

Only these six implementation objects and two new tool rows change. The frontend
summary's Phase 7 classification is explicitly corrected to Phase 3 to match its
existing read-only source/OpenAPI representations. Dispositions, existing
requirements, other classifications and unrelated fingerprints are preserved.
Website schema, ordering and provider/action APIs remain unchanged.

## Local evidence and remaining gates

- Service/SQL tests and existing website email contract/decomposition regressions:
  **36 passed in 5.12 seconds**. Coverage includes exact canonical counts and
  readiness parity, no-agency and inactive-agency behavior, foreign-owner
  exclusion, all seven scalar projections, provider-specific nonblank credential
  presence, complete-envelope limits, typed count bounds and safe deadlines.
- Actual OAuth/MCP HTTP tests: **21 passed in 24.80 seconds**. They prove fixed
  argument-free tool schemas, count/status results and content-free audits,
  eight current-authority denial variants for both tools, no email writes or
  durable operations, and static timeout/size/unexpected failures with clean retry.
- Independent PostgreSQL component tests: **16 passed in 5.09 seconds**, retaining
  synthetic schema `manual_review_c5361106b1964e14942203297de12346`. They cover
  exact UTC/JSON-false/null/missing predicates, personal ownership across both
  agencies including inactive/no-agency cases, seven scalar counts with a 2 MiB
  unrelated evidence value excluded from ORM hydration, configuration-only status
  with provider/storage tripwires, current authority denials, real source/grant
  waits with timeout and retry, identity serialization, external cancellation and
  hashes proving every mailbox business column unchanged. Tables are ORM-created
  in a retained isolated schema on loopback PostgreSQL; this is not migration,
  restricted-role, production memory or combined-load qualification. No public
  business/control rows are changed and no data/schema is removed.
- Four new source modules pass strict mypy. Scoped Ruff, the architecture
  verifier's four explicitly reviewed infrastructure edges and all 87 backend
  quality budgets pass. The existing route helper ceiling is retained.
- Inventory classification passes for this branch's 1,503 surfaces and 78 tools;
  all 12 inventory drift tests pass. A parsed comparison proves only the six
  implementation records, two new tools and approved single phase correction
  changed, preserving dispositions and unrelated records.

Ignored receipts are `outputs/mcp-email-overview-service.xml` and
`outputs/mcp-email-overview-http.xml`, plus the independent
`outputs/mcp-email-overview-postgresql.xml`. Tests use the existing Python 3.11 runtime
with this isolated checkout's backend as the working directory. No production
grants, control settings, schema, providers, services or data were changed.
The later release passed the combined 6,132-test backend regression. A separate
immutable v2 saved-Codex runner completed exactly three calls in 133.281 seconds:
connection status, email readiness and personal summary. All six readiness flags
and both provider configuration-presence flags were true; all seven personal
counts were zero and matched the earlier loaded authenticated website. These are
separate live observations, not an atomic snapshot or provider/delivery-health
proof. The original 82.235-second incomplete two-call attempt remains retained
with `missing_call`; its cause was not established. See the
[release checkpoint](mcp-read-observations-release-checkpoint.md) for the safe
acceptance/hash bindings and precise limitations. Same-host capacity and the
broader phase gates remain open.
