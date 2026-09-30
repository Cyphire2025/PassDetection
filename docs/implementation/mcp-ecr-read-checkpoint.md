# Standalone ECR list and detail read checkpoint

Local implementation checkpoint, 2026-09-30. `list_ecr_batches` and
`get_ecr_batch` provide the standalone ECR checker list/detail family through
`mcp:read`. The six existing frontend, source and OpenAPI ledger rows and two new
tools are `implemented_unverified`, Phase 3. The combined full backend aggregate,
deployment, actual Codex readback and combined capacity qualification remain
pending for this slice. Other ECR workflows and the eight-phase goal remain open.

The [shared repository](../../backend/app/infrastructure/repositories/ecr_read_repository.py)
extracts the exact website role/agency/staff predicates and six SQL item counters.
The [existing website routes](../../backend/app/presentation/api/v1/routes/ecr_checker.py)
retain their HTTP shapes, status codes, latest-50 list, item ordering and mutation
semantics. The reviewed OpenAPI snapshot is unchanged. The MCP service requires a
current active Superadmin grant with `mcp:read`, then reads the actor's current
agency and holds its active-agency shared lock for the read transaction. No agency
argument or impersonation is accepted. A missing/inactive agency is denied; an
active agency with no batches returns a complete empty page. Staff creator-only
visibility remains the website's canonical policy; this does not grant staff MCP
connection eligibility. A cross-agency or missing batch has one static unavailable
outcome.

`list_ecr_batches(page_size=50, cursor=null)` returns batch IDs, titles, status,
expected count, creation time and six live counts: total items, processed
(completed or failed), ECR, NA, needs-review and failed. Pages use `created_at DESC,
id DESC`, with size 1 to 100 and no total latest-50 ceiling. `get_ecr_batch(batch_id,
page_size=50, cursor=null)` returns the same whole-batch summary plus item ID,
client ID, original filename, status, result, reason and creation time. Items use
the website's `created_at ASC, id ASC` order; duplicate filenames are retained as
separate identified rows. Empty batches are readable.

Thirty-minute signed cursors bind actor, current agency, query type, exact batch,
page size, creation cutoff and last timestamp/UUID. Changing any binding requires
restarting the read. Newly created rows beyond the cutoff are excluded, while
statuses and counters remain live. Backdated insertions, deletions and concurrent
updates can still change a later page. Each response explicitly states that no
atomic snapshot is guaranteed. Whole-batch counts cover all current items,
independently of the cutoff and returned page. They are not inferred from page
length and are not evidence of a current file, successful processing or delivery.

The repository selects scalar columns only. SQL projects at most 161 title
characters or 256 filename/reason characters; the extra character detects values
beyond the canonical 160/255 limits, and the service rejects the page rather than
silently truncating it. Each page reads at most `page_size + 1` rows. Counters are
aggregated in SQL; no ECR batch/item ORM objects, storage locators, content hashes,
processing leases, model names or token usage are materialized by the MCP read.
Titles, filenames and reasons remain authorized, untrusted business text.

The service read, including its fresh authority and agency checks, has a five-second
application deadline. The complete ASCII-escaped structured response is limited
to 256 KiB, accounting for the shared invocation's environment, revision, timestamp
and audit ID. A large Unicode page produces a static limit error and can be
retried with a smaller page; source text is never returned partly truncated.
Existing transport/token-verification/audit time limits remain separate. Timeout,
invalid cursor, unavailable scope and limit responses use code-owned text without
SQL, provider errors or source contents. Cancellation leaves rollback to the shared
invocation/caller; real PostgreSQL retry tests prove the session can be reused
after rollback.

There is no upload, processing, retry, AI/provider/storage call, file access,
export, deletion, operation receipt or idempotency key. The shared invocation audit
is the only MCP effect. These reads do not implement ECR batch creation, image
upload, processing/retry or ECR workbook exports; those ledger rows stay planned.

## Local evidence

- [SQL/SDK/HTTP tests](../../backend/tests/integration/test_mcp_ecr_reads.py):
  **37 passed** against the final source, including actual website/MCP equality,
  public SDK schemas and read annotations, 107 tied batches beyond the website
  ceiling, ascending duplicate filenames, live counts across a cutoff, cursor
  tampering/binding/expiry, current grant/account/agency denial, canonical website
  roles, scalar-only SQL and no business writes, source sentinels, real Unicode
  response overflow, deadline errors and safe rejection audits.
- The same new suite plus [existing website ECR regressions](../../backend/tests/unit/presentation/test_ecr_checker.py)
  passed **60 tests** before the final envelope-only budget refinement. The final
  37-test rerun covers that refinement; the 23 website tests use unchanged bytes
  from their passing run. These counts overlap and must not be added as separate
  suites.
- [Independent PostgreSQL tests](../../backend/tests/service_integration/test_mcp_ecr_reads_postgresql.py):
  **26 passed in 6.59 seconds** on final source, using the dedicated loopback
  PostgreSQL 16.15 database and a new retained schema
  `manual_review_50ae803556c249a1937b01c52563d82f`. The lane proves current scope and
  exact counters, 107 tied batches and creation cutoff, ascending item pagination
  with changing totals, private-column/ORM exclusion, all authority/cursor cases,
  Unicode limits and database-side sentinels, actual batch/item table-lock
  deadline cancellation, and external cancellation during the account lock wait
  followed by rollback and a clean retry. No public business/control records were
  changed or cleaned up. These are isolated ORM-created tables, not migration,
  restricted-runtime-role, production or load qualification.
- Strict mypy on the five affected production modules, scoped Ruff, all 87 backend
  quality budgets and the architecture validator pass. Six exact infrastructure
  import edges were reviewed and recorded; no validator or budget was relaxed.
- Inventory reports **1,497 surfaces / 72 tools** in this isolated checkout and
  all **12 drift tests pass**. An exact parsed comparison limits ledger changes
  to the six ECR list/get requirements and implementation objects plus two new
  tool rows. Existing classifications, phases, fingerprints and every other row
  remain unchanged. The two frontend rows' generic mutation requirements are
  replaced by the reviewed read contract, not by an exclusion.

Ignored local receipts are `outputs/mcp-ecr-focused.xml`,
`outputs/mcp-ecr-focused-final.xml` and `outputs/mcp-ecr-reads-postgresql.xml`.
The complete combined backend aggregate is deliberately left to integration;
this checkpoint does not assert it has passed or promote any phase gate.
