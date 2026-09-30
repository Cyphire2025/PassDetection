# Document rename metadata read checkpoint

Locally qualified on 2026-09-30. Two metadata read tools implement six existing
website surface representations. The ledger remains `implemented_unverified`:
component tests do not establish deployed acceptance, completion of Phase 3,
or combined production capacity. Integration and the next combined full backend
regression remain pending at this checkpoint.

`list_document_rename_batches` and `get_document_rename_batch` require current
`mcp:read` authority and an active Superadmin. The current grant and identity are
locked within the read deadline, including deployment capability checks. Agency
scope comes from that identity; callers cannot supply a user, agency or effective
role. Shared website scope rejects missing agency and coordinators, and preserves
the staff creator restriction. The existing website does not require an active
Agency for these reads; this slice adds no such policy. An inactive agency fixture
explicitly preserves that behavior. Foreign or missing batches return the same
fixed unavailable error.

The website retains its latest-100 batch window and existing ordering. MCP uses
complete signed, actor/current-agency/page-bound keyset pagination over retained
authorized batches, with a creation cutoff and `created_at DESC, id DESC` ties.
The default and maximum page size are 100, with one bounded lookahead. Older
batches remain reachable. Detail pages use `renamed_filename ASC, id ASC`, numeric
pages and at most 100 rows. A scoped scalar count rejects more than the canonical
1,500 uploaded items before any item projection. All 1,500 permitted items are
reachable; exceeding the bound fails explicitly rather than silently omitting
items. Stored batch counters are preserved as recorded, separately from the
current item count and page metadata.

Both paths return live observations. Creation cutoffs do not freeze later edits
or deletions. Detail count, recorded counters and filename-ordered pages are
separate observations; concurrent edits can shift page membership. The response
explicitly disclaims an atomic snapshot. A second scoped parent lookup rejects a
batch removed or moved during a detail read. It does not claim to lock or snapshot
all source documents.

Scalar projections bound text in SQL with one sentinel character, then reject
oversized values before returning a partial result. Bounds are: batch title 160,
batch/item status 32, filenames 255, detected type 32, reason 255, extracted name 255,
passport number 32 and reference 80 characters. No full batch/item ORM objects or
arbitrary document content is hydrated. Each read has a 10-second deadline covering
current authority, database reads and any sensitive-read audit, and a conservative
256 KiB ASCII-escaped JSON bound for the **complete structured response**, including
actual environment/revision and fixed-width observation time/audit UUID. The
normal detail service path uses nine SQL statements before optional sensitive
audit; common transport authorization/invocation audit are additional. This is a
component bound, not a measured production memory or mixed-load guarantee.

The default omits extracted names, passport numbers and references at SQL source.
`include_extracted_identifiers=true` exposes those three bounded fields and records
`document_rename.mcp_identifiers_read` with actor/agency/batch/grant and page/count
metadata only. No title, filename, reason or extracted value enters that audit.
Titles, filenames and reasons may already contain personal information even when
extracted identifiers are omitted. All returned text is explicitly untrusted
business content, never an instruction or authority to perform another action.

`download_metadata_eligible` shares the website's supported-type, non-rejected
status and recorded storage-key presence test. SQL returns key presence as a
boolean; no key or URL is materialized. Eligibility does not establish file
existence or authorize a download. These tools never analyze, rename, create,
delete, download, access storage, invoke a provider, send a message, enqueue work,
or create durable operations/export history/artifacts.

## Exact six existing surface rows

1. `frontend:frontend/features/documents/api/document-rename.api.ts:listBatches`
2. `frontend:frontend/features/documents/api/document-rename.api.ts:getBatch`
3. `openapi:GET:/api/v1/document-rename/batches`
4. `openapi:GET:/api/v1/document-rename/batches/{batch_id}`
5. `route:backend/app/presentation/api/v1/routes/document_rename.py:list_rename_batches:GET:/batches`
6. `route:backend/app/presentation/api/v1/routes/document_rename.py:get_rename_batch:GET:/batches/{batch_id}`

Only these six implementation objects and two new MCP tool rows change in the
coverage matrix. Existing classifications, requirements, phase assignments and
unrelated fingerprints are retained. Website response schemas, routes and existing
download URLs remain unchanged; MCP deliberately returns metadata only.

## Retained evidence

- [Service/scalar SQL tests](../../backend/tests/integration/test_mcp_rename_reads.py),
  [actual OAuth/SDK HTTP tests](../../backend/tests/integration/test_mcp_rename_http.py)
  and unchanged website rejection tests: **55 passed in 25.57 seconds**. They cover
  canonical parity, inactive/no/foreign agency handling, staff/coordinator policy,
  full cursor coverage and binding, fixed field/input/complete-envelope bounds,
  safe source projection, current authority denials, parent scope change, exact
  content-free sensitive audit and absence of business/file side effects.
- [PostgreSQL component tests](../../backend/tests/service_integration/test_mcp_rename_reads_postgresql.py):
  **8 passed in 3.26 seconds** in retained synthetic schema
  `manual_review_9477febce2e1476aa76dcb30cdf0a914`. Evidence covers 109 authorized
  retained batches, all 1,500 filename-ordered items, canonical first-window size
  and exact detail parity, nine-statement scalar projection, 1,501 rejection before
  item hydration, Unicode complete-response limits with smaller-page recovery,
  foreign source exclusion, real blocked-source/grant cancellation followed by
  rollback and retry, and identity updates blocked through a sensitive read.
  Tables are ORM-created in a dedicated schema on loopback PostgreSQL; this is
  not migration, restricted-runtime-role or production load qualification. No
  public business/control rows are changed and no schema/data is removed.
- Independent review extended the same PostgreSQL module to **25 passed in
  4.90 seconds**, retaining schema `manual_review_5fd8edfa0ca84160aac25fa70a9f5ea6`.
  The additional cases cover current grant/identity/agency denial, shared
  staff/coordinator and inactive-agency policy, cursor actor/scope/page/expiry
  binding, creation cutoff, preservation of all business columns with only the
  intended sensitive audit, and external cancellation/audit rollback followed
  by retry. The first independent run found a test expectation disagreement
  about the canonical supported document types; only that assertion was
  corrected, with no application change. Its failed receipt is retained.

Five source modules pass strict mypy; scoped Ruff, all 87 backend quality budgets
and the architecture verifier pass. The architecture policy records exactly six
reviewed infrastructure import edges. Inventory classification passes for 1,499
surfaces and 74 tools in this isolated branch; all 12 inventory drift tests pass.
A parsed matrix comparison preserves all unrelated records and fingerprints.

Ignored receipts are `outputs/mcp-rename-focused.xml`,
`outputs/mcp-rename-postgresql.xml` and
`outputs/mcp-rename-reads-independent-postgresql-2.xml`.
The existing Python 3.11 environment executes
with this isolated checkout's backend as its explicit working directory. The
production read/export profile, grants, schema and control settings are unchanged.
Real deployed Codex invocation, full combined regression and same-host capacity
qualification remain separate gates.
